import test from "node:test";
import assert from "node:assert/strict";

import {
  CHILD_BINDING_KEY,
  CHILD_INSTALLATION_KEY,
  cameraQrIsSupported,
  childBindingIsActive,
  forgetActiveChildBinding,
  getOrCreateInstallationId,
  normalizeQrToken,
  rememberActiveChildBinding,
  startCameraQrScanner,
} from "../scanner.mjs";

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    values,
  };
}

function scannerFixture() {
  let scheduled;
  let trackStopped = false;
  const video = {
    readyState: 2,
    videoWidth: 1280,
    videoHeight: 720,
    srcObject: null,
    play: async () => {},
    pause: () => {},
  };
  const mediaDevices = {
    getUserMedia: async () => ({
      getTracks: () => [{ stop: () => { trackStopped = true; } }],
    }),
  };
  return {
    video,
    mediaDevices,
    schedule: (callback) => { scheduled = callback; return 1; },
    cancel: () => {},
    runFrame: async () => scheduled(),
    trackWasStopped: () => trackStopped,
  };
}

test("installation and active marker persist without storing the QR token", () => {
  const storage = memoryStorage();
  const cryptoImpl = { randomUUID: () => "12345678-1234-1234-1234-123456789abc" };

  const first = getOrCreateInstallationId(storage, cryptoImpl);
  const second = getOrCreateInstallationId(storage, { randomUUID: () => "other-value" });

  assert.equal(first, "child_12345678-1234-1234-1234-123456789abc");
  assert.equal(second, first);
  assert.equal(storage.values.get(CHILD_INSTALLATION_KEY), first);
  assert.equal(childBindingIsActive(storage), false);
  assert.equal(rememberActiveChildBinding(storage), true);
  assert.equal(storage.values.get(CHILD_BINDING_KEY), "active");
  assert.equal(childBindingIsActive(storage), true);
  assert.equal(forgetActiveChildBinding(storage), true);
  assert.equal(childBindingIsActive(storage), false);
  assert.deepEqual([...storage.values.values()], [first]);
});

test("QR tokens are trimmed, bounded, and otherwise preserved for the backend", () => {
  assert.equal(normalizeQrToken("  ling://bind/LING-DEMO-2026  "), "ling://bind/LING-DEMO-2026");
  assert.equal(normalizeQrToken("LING-DEMO-2026"), "LING-DEMO-2026");
  assert.equal(normalizeQrToken(" "), "");
  assert.equal(normalizeQrToken("x".repeat(513)), "");
});

test("camera support accepts either BarcodeDetector or the jsQR fallback", () => {
  const mediaDevices = { getUserMedia: async () => {} };
  assert.equal(cameraQrIsSupported(class {}, mediaDevices, undefined), true);
  assert.equal(cameraQrIsSupported(undefined, mediaDevices, () => {}), true);
  assert.equal(cameraQrIsSupported(undefined, mediaDevices, undefined), false);
});

test("native BarcodeDetector reads the raw QR value and releases the camera", async () => {
  const fixture = scannerFixture();
  let result = "";
  class Detector {
    async detect() {
      return [{ rawValue: "ling://bind/LING-DEMO-2026" }];
    }
  }

  await startCameraQrScanner(fixture.video, {
    BarcodeDetectorImpl: Detector,
    mediaDevices: fixture.mediaDevices,
    schedule: fixture.schedule,
    cancel: fixture.cancel,
    onResult: (value) => { result = value; },
  });
  await fixture.runFrame();

  assert.equal(result, "ling://bind/LING-DEMO-2026");
  assert.equal(fixture.trackWasStopped(), true);
  assert.equal(fixture.video.srcObject, null);
});

test("jsQR decodes a camera frame when BarcodeDetector is unavailable", async () => {
  const fixture = scannerFixture();
  const draws = [];
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ({
      drawImage: (...args) => draws.push(args),
      getImageData: (_x, _y, width, height) => ({
        data: new Uint8ClampedArray(width * height * 4),
        width,
        height,
      }),
    }),
  };
  let result = "";

  await startCameraQrScanner(fixture.video, {
    BarcodeDetectorImpl: undefined,
    jsQrImpl: () => ({ data: "LING-DEMO-2026" }),
    canvasFactory: () => canvas,
    mediaDevices: fixture.mediaDevices,
    schedule: fixture.schedule,
    cancel: fixture.cancel,
    onResult: (value) => { result = value; },
  });
  await fixture.runFrame();

  assert.equal(result, "LING-DEMO-2026");
  assert.equal(canvas.width, 720);
  assert.equal(canvas.height, 405);
  assert.equal(draws.length, 1);
  assert.equal(fixture.trackWasStopped(), true);
});
