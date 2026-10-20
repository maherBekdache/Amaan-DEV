// Web only: expo-camera's QR reader (barcode-detector / zxing-wasm) would download its
// decoder from a CDN at run time. Serve it from the app instead (public/, copied on npm install).
import { setZXingModuleOverrides } from "barcode-detector/ponyfill";

setZXingModuleOverrides({
  locateFile: (path: string, prefix: string) => (path.endsWith(".wasm") ? "/zxing_reader.wasm" : prefix + path),
});
