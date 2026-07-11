export const CHILD_INSTALLATION_KEY = "ling-child-installation-v1";
export const CHILD_BINDING_KEY = "ling-child-binding-v1";

function readStorage(storage, key) {
  try {
    return storage?.getItem(key) || "";
  } catch {
    return "";
  }
}

function writeStorage(storage, key, value) {
  try {
    storage?.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

function removeStorage(storage, key) {
  try {
    storage?.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

function randomInstallationId(cryptoImpl) {
  if (typeof cryptoImpl?.randomUUID === "function") {
    return `child_${cryptoImpl.randomUUID()}`;
  }

  const bytes = new Uint8Array(16);
  cryptoImpl?.getRandomValues?.(bytes);
  const token = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `child_${token || `${Date.now()}`}`;
}

export function getOrCreateInstallationId(
  storage = globalThis.localStorage,
  cryptoImpl = globalThis.crypto,
) {
  const current = readStorage(storage, CHILD_INSTALLATION_KEY);
  if (/^child_[A-Za-z0-9-]{8,80}$/.test(current)) return current;

  const installationId = randomInstallationId(cryptoImpl);
  writeStorage(storage, CHILD_INSTALLATION_KEY, installationId);
  return installationId;
}

export function childBindingIsActive(storage = globalThis.localStorage) {
  return readStorage(storage, CHILD_BINDING_KEY) === "active";
}

export function rememberActiveChildBinding(storage = globalThis.localStorage) {
  return writeStorage(storage, CHILD_BINDING_KEY, "active");
}

export function forgetActiveChildBinding(storage = globalThis.localStorage) {
  return removeStorage(storage, CHILD_BINDING_KEY);
}

export function normalizeQrToken(value) {
  const token = String(value || "").trim();
  return token.length > 0 && token.length <= 512 ? token : "";
}

export function cameraQrIsSupported(
  BarcodeDetectorImpl = globalThis.BarcodeDetector,
  mediaDevices = globalThis.navigator?.mediaDevices,
  jsQrImpl = globalThis.jsQR,
) {
  const hasDecoder = typeof BarcodeDetectorImpl === "function" || typeof jsQrImpl === "function";
  return hasDecoder && typeof mediaDevices?.getUserMedia === "function";
}

export async function startCameraQrScanner(video, options = {}) {
  const {
    BarcodeDetectorImpl = globalThis.BarcodeDetector,
    mediaDevices = globalThis.navigator?.mediaDevices,
    jsQrImpl = globalThis.jsQR,
    canvasFactory = () => globalThis.document.createElement("canvas"),
    onResult = () => {},
    onError = () => {},
    schedule = (callback) => globalThis.setTimeout(callback, 180),
    cancel = (timer) => globalThis.clearTimeout(timer),
  } = options;

  if (!cameraQrIsSupported(BarcodeDetectorImpl, mediaDevices, jsQrImpl)) {
    throw new Error("camera_qr_unsupported");
  }

  let detector = null;
  if (typeof BarcodeDetectorImpl === "function") {
    try {
      detector = new BarcodeDetectorImpl({ formats: ["qr_code"] });
    } catch {
      detector = null;
    }
  }
  if (!detector && typeof jsQrImpl !== "function") throw new Error("camera_qr_unsupported");

  const canvas = detector ? null : canvasFactory();
  const context = canvas?.getContext("2d", { willReadFrequently: true });
  if (!detector && !context) throw new Error("camera_qr_unsupported");
  const stream = await mediaDevices.getUserMedia({
    audio: false,
    video: { facingMode: { ideal: "environment" } },
  });
  let stopped = false;
  let timer = null;

  const stop = () => {
    if (stopped) return;
    stopped = true;
    if (timer !== null) cancel(timer);
    stream.getTracks().forEach((track) => track.stop());
    video.pause?.();
    video.srcObject = null;
  };

  const scan = async () => {
    if (stopped) return;
    try {
      if (video.readyState >= 2) {
        let rawValue = "";
        if (detector) {
          const codes = await detector.detect(video);
          rawValue = codes.find((code) => code?.rawValue)?.rawValue;
        } else if (video.videoWidth > 0 && video.videoHeight > 0) {
          const scale = Math.min(1, 720 / Math.max(video.videoWidth, video.videoHeight));
          canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
          canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
          context.drawImage(video, 0, 0, canvas.width, canvas.height);
          const frame = context.getImageData(0, 0, canvas.width, canvas.height);
          rawValue = jsQrImpl(frame.data, frame.width, frame.height, {
            inversionAttempts: "dontInvert",
          })?.data;
        }
        const token = normalizeQrToken(rawValue);
        if (token) {
          stop();
          onResult(token);
          return;
        }
      }
    } catch (error) {
      onError(error);
    }
    if (!stopped) timer = schedule(scan);
  };

  try {
    video.srcObject = stream;
    await video.play();
    timer = schedule(scan);
    return stop;
  } catch (error) {
    stop();
    throw error;
  }
}
