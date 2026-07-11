# 即梦 / Seedance 视频生成链路

## 目标

真实视频生成是可替换的后台能力，不进入实时语音热路径，也不能成为黑客松演示的单点故障。默认仍使用 `MockMediaProvider`；显式配置后，`JimengArkProvider` 通过火山方舟 Seedance 2.0 异步 API 生成 9:16、5-7 秒视频。

官方接口返回的视频和尾帧 URL 只保留 24 小时，因此远端任务 `succeeded` 不等于产品已发布。只有视频下载、校验和本地原子落盘全部成功后，本地任务才进入 `succeeded`，APP 才能看见该瞬间。

## 生命周期

```text
业务事务
  moment.rendering + generation_job.queued + request_json
        |
        | 提交事务后，由后台 worker 处理
        v
Seedance create task -> external_task_id -> generation_job.running
        |
        | 每 10 秒轮询；临时错误指数退避
        v
remote succeeded -> 下载 MP4 / last frame -> 校验 -> .part 原子重命名
        |
        v
generation_job.succeeded -> moment.published
        |
        v
APP 读取 /generated-media/<immutable-file>.mp4
```

业务事务不访问网络。`request_json` 会冻结 prompt、模型、参考图、分辨率、时长和画幅；`external_task_id`、远端响应、下一次轮询时间、失败次数和本地文件元数据也全部持久化在 SQLite。服务重启或环境变量变化后，worker 仍会按 job 创建时的契约继续处理 `moment.status=rendering` 的最新任务。

## 配置

```bash
export LING_MEDIA_PROVIDER=jimeng
export ARK_API_KEY=...
export LING_ARK_VIDEO_MODEL=doubao-seedance-2-0-260128
export LING_ARK_VIDEO_REFERENCE_IMAGE_URL=https://公开可读的角色定妆图.png
export LING_ARK_VIDEO_DURATION_SECONDS=6
export LING_ARK_VIDEO_RESOLUTION=720p
./run.sh
```

参考图片使用官方多模态输入格式 `image_url + role=reference_image`。URL 必须能被方舟服务公网访问，生产环境建议放在火山 TOS；不要把本地路径或临时登录 URL写进配置。

`ARK_API_KEY` 只存在后端环境变量中，不写数据库、不下发 APP。RTC 的 `VOLCENGINE_ACCESS_KEY` / `VOLCENGINE_SECRET_KEY` 不能替代方舟 API Key。

未设置 `LING_MEDIA_PROVIDER` 时默认使用 Mock。即使显式设置为 `jimeng`，只要 `ARK_API_KEY` / `LING_ARK_VIDEO_API_KEY` 均为空，服务也会自动降级到 Mock：正常启动、不访问方舟、不创建或积压真实生成 job。补上 Key 后只影响此后新建的任务，不会突然补跑降级期间已经由 Mock 完成的瞬间。可通过 `/api/admin/media/jobs` 的 `requested_provider`、`provider`、`degraded` 与 `degraded_reason` 查看当前状态。

## 任务完成策略

- 默认轮询间隔：10 秒；后台 worker 每 2 秒扫描一批本地任务，但未到 `next_poll_at` 时不会访问远端。
- 默认远端任务超时：30 分钟；可通过 `LING_ARK_VIDEO_TIMEOUT_SECONDS` 调整，官方允许更长执行窗口。
- 429、5xx、网络超时和下载中断：指数退避，默认最多 5 次 provider 失败。
- 400、401、403 等永久错误：当前 generation attempt 立即失败；产品层沿用现有规则最多再发起一次 attempt。
- 服务退出：worker 最多等待 5 秒停止；已提交的远端任务 ID 保存在数据库，重启后继续。
- APP 主动轮询 `/api/moments/{id}` 与后台 worker 可以同时存在；数据库租约避免并发重复创建同一远端任务。

方舟当前公开的 create 接口没有可用的幂等键。极端情况下，如果进程在方舟已接受 POST、但本地尚未写回 `external_task_id` 的几毫秒窗口内崩溃，恢复后可能再次提交并产生一条多余远端任务。单实例黑客松 Demo 接受这个边界；正式生产应增加 callback/reconciliation 或由具备幂等能力的任务网关代理提交。

## 文件保存与发布

默认目录为 `data/generated_media/`，整个 `data/` 已被 Git 忽略。文件名由本地 job ID 与远端 task ID 哈希组成，不采信远端文件名：

```text
job-<job_id>-<task_hash>.mp4
job-<job_id>-<task_hash>.png|jpg|webp
```

下载先写隐藏 `.part` 文件；MP4 必须包含合法 `ftyp` 文件头，poster 必须是 PNG、JPEG 或 WebP，单个下载默认不超过 100 MiB。校验成功后使用同目录原子重命名。视频 SHA-256、poster SHA-256、尺寸、时长、模型、远端 task ID 与 prompt hash 会进入不可变发布快照。

方舟未返回尾帧或尾帧下载失败时，视频仍可发布，但沿用同事件的本地预生成 poster。生成完成后的 APP 数据协议不变：

```json
{
  "media": {
    "src": "/generated-media/job-12-a1b2c3d4.mp4",
    "poster": "/generated-media/job-12-a1b2c3d4.png",
    "mime_type": "video/mp4"
  }
}
```

生产环境可将 `LING_GENERATED_MEDIA_ROOT` 指向持久卷；多实例和正式上线应进一步替换为 TOS 对象存储，但 APP 投影协议无需改变。

## 运维入口

以下入口属于现有受保护 admin API，只允许本机或管理令牌访问：

```bash
curl http://127.0.0.1:8888/api/admin/media/jobs
curl -X POST http://127.0.0.1:8888/api/admin/media/tick
```

也可以不用启动 Web 服务，手动驱动持久化任务：

```bash
uv run python -m backend.media_worker --once
uv run python -m backend.media_worker --until-idle --timeout 1800
```

`video-prompts/worldline/` 中的提示词用于离线预生成基础世界素材；实时专属瞬间则由 manifest 中已审核的事件语义、故事和角色约束自动组装提示词。两者都不允许模型自行新增世界事实。

## 黑客松演示

现场保持：

```bash
LING_MEDIA_PROVIDER=mock ./run.sh
```

真实生成用于离线准备素材或加分演示。即梦/方舟不可用、余额不足或网络失败时，不会影响 Mock 主演示链路。

## Change log

- `2026-07-11`：纳入统一文档索引；确认配置、worker 命令和 admin 路由与当前代码一致。
