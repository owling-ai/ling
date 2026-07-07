"""包初始化：自动加载项目根目录的 .env（无依赖实现）。

规则：
- 支持 KEY=VALUE 与 export KEY=VALUE 两种写法，# 开头为注释，引号会被剥掉
- 只填补空缺：shell 里已存在的环境变量优先于 .env
- 必须在任何子模块 import 之前执行（llm.py 在模块级读取这些变量）
"""
import os
import sys


def _load_dotenv():
    path = os.path.join(os.path.dirname(__file__), "..", ".env")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return
    seen = set()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if not key:
            continue
        if key in seen:
            print(f"[env] ⚠️ .env 里 {key} 出现多次，只有第一行生效，后面的被忽略", file=sys.stderr)
            continue
        seen.add(key)
        if key not in os.environ:
            os.environ[key] = value


_load_dotenv()
