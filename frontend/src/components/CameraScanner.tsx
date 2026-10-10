import { useCallback, useEffect, useRef, useState } from "react";
import jsQR from "jsqr";

interface Props {
  onCapture: (frame: Blob) => void;
  onClose: () => void;
}

/**
 * Live QR scanning with the laptop/desktop webcam.
 *
 * The video never leaves the browser. jsQR only *detects* that a QR code is
 * in view; we then send that single still frame to the local backend, which
 * decodes and checks it with the same pipeline as uploaded images. Nothing
 * decoded here is opened or followed.
 */
export default function CameraScanner({ onCapture, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number>(0);
  const doneRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState("Starting camera…");

  const stop = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const captureFrame = useCallback(() => {
    const video = videoRef.current;
    if (!video || !video.videoWidth || doneRef.current) return;
    doneRef.current = true;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")!.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      stop();
      if (blob) onCapture(blob);
    }, "image/png");
  }, [onCapture, stop]);

  useEffect(() => {
    let cancelled = false;
    doneRef.current = false;

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("This browser does not allow camera access here. Use http://localhost, or upload a photo instead.");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: deviceId ? { deviceId: { exact: deviceId } } : { facingMode: "environment", width: { ideal: 1280 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        const video = videoRef.current!;
        video.srcObject = stream;
        await video.play();
        const all = await navigator.mediaDevices.enumerateDevices();
        setDevices(all.filter((d) => d.kind === "videoinput"));
        setStatus("Point the camera at a QR code");
        scan();
      } catch (e) {
        const name = (e as DOMException)?.name;
        setError(
          name === "NotAllowedError"
            ? "Camera permission was denied. Allow it in the browser's address bar, or upload a photo instead."
            : name === "NotFoundError"
              ? "No camera was found on this computer."
              : "Could not start the camera.",
        );
      }
    }

    const work = document.createElement("canvas");
    let last = 0;
    function scan(ts = 0) {
      rafRef.current = requestAnimationFrame(scan);
      if (ts - last < 200 || doneRef.current) return; // ~5 checks per second
      last = ts;
      const video = videoRef.current;
      if (!video || video.readyState < 2) return;
      const scale = Math.min(1, 640 / video.videoWidth);
      work.width = Math.round(video.videoWidth * scale);
      work.height = Math.round(video.videoHeight * scale);
      const ctx = work.getContext("2d", { willReadFrequently: true })!;
      ctx.drawImage(video, 0, 0, work.width, work.height);
      const img = ctx.getImageData(0, 0, work.width, work.height);
      const hit = jsQR(img.data, img.width, img.height, { inversionAttempts: "attemptBoth" });
      if (hit) {
        setStatus("QR code found, analyzing…");
        captureFrame();
      }
    }

    start();
    return () => {
      cancelled = true;
      stop();
    };
  }, [deviceId, captureFrame, stop]);

  return (
    <div className="rounded-2xl border border-slate-200 bg-black/90 p-3 text-white">
      {error ? (
        <p className="p-6 text-center text-sm">{error}</p>
      ) : (
        <div className="relative mx-auto aspect-video max-h-[360px] overflow-hidden rounded-xl bg-black">
          <video ref={videoRef} className="h-full w-full object-contain" muted playsInline />
          <div className="pointer-events-none absolute inset-[18%] rounded-xl border-2 border-teal-300/80" />
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <span className="mr-auto text-slate-300">{error ? "" : status}</span>
        {devices.length > 1 && (
          <select
            className="rounded-md bg-slate-800 px-2 py-1"
            value={deviceId ?? ""}
            onChange={(e) => setDeviceId(e.target.value || undefined)}
          >
            <option value="">Default camera</option>
            {devices.map((d, i) => (
              <option key={d.deviceId} value={d.deviceId}>
                {d.label || `Camera ${i + 1}`}
              </option>
            ))}
          </select>
        )}
        {!error && (
          <button
            className="rounded-md bg-teal-600 px-3 py-1 font-medium hover:bg-teal-500"
            onClick={captureFrame}
            title="Send the current frame (e.g. several QR codes in view)"
          >
            Capture now
          </button>
        )}
        <button
          className="rounded-md bg-slate-700 px-3 py-1 hover:bg-slate-600"
          onClick={() => {
            stop();
            onClose();
          }}
        >
          Close camera
        </button>
      </div>
    </div>
  );
}
