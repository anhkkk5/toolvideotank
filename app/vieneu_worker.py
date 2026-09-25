import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    from vieneu import Vieneu
except ImportError:
    Vieneu = None

LOADED_MODELS = {}



def get_or_load_model(model_path: str):
    norm_path = os.path.normpath(model_path)
    if norm_path not in LOADED_MODELS:
        print(f"[VieNeu Server] Caching model: {norm_path}...", flush=True)
        tts = Vieneu(
            mode="v3turbo",
            backbone_repo=norm_path,
            backend="pytorch",
            device="cpu",
            dtype="float32",
        )
        LOADED_MODELS[norm_path] = tts
        print(f"[VieNeu Server] Model cached successfully: {norm_path}", flush=True)
    return LOADED_MODELS[norm_path]


class VieNeuRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Tắt log HTTP mặc định để console sạch đẹp
        pass

    def do_GET(self):
        if self.path == "/ping":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "status": "ready"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/synthesize":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                data = json.loads(body)

                text = str(data.get("text", "")).strip()
                model_path = str(data.get("model", "")).strip()
                voice = str(data.get("voice", "")).strip()
                output_path = str(data.get("output", "")).strip()

                if not text:
                    raise ValueError("TTS text is empty.")
                if not model_path:
                    raise ValueError("Model path is required.")
                if not output_path:
                    raise ValueError("Output path is required.")

                tts = get_or_load_model(model_path)
                audio = tts.infer(text, voice=voice)
                os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                tts.save(audio, output_path)

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "output": output_path}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
        elif self.path == "/shutdown":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
            def kill():
                import time
                time.sleep(0.5)
                os._exit(0)
            import threading
            threading.Thread(target=kill).start()
        else:
            self.send_response(404)
            self.end_headers()


def run_server(port: int = 53239, preload_model: str = ""):
    if preload_model and os.path.isdir(preload_model):
        try:
            get_or_load_model(preload_model)
        except Exception as e:
            print(f"[VieNeu Server] Preload warning: {e}", flush=True)

    server = HTTPServer(("127.0.0.1", port), VieNeuRequestHandler)
    print(f"[VieNeu Server] Running at http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def run_cli(args):
    text = sys.stdin.read().strip()
    if not text:
        raise ValueError("TTS text is empty.")

    print("[VieNeu] Loading model...", flush=True)
    tts = Vieneu(
        mode="v3turbo",
        backbone_repo=args.model,
        backend="pytorch",
        device="cpu",
        dtype="float32",
    )
    print("[VieNeu] Synthesizing...", flush=True)
    audio = tts.infer(text, voice=args.voice)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    tts.save(audio, args.output)
    print(f"[VieNeu] Saved: {args.output}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", action="store_true", help="Run in persistent daemon server mode")
    parser.add_argument("--port", type=int, default=53239, help="Server port")
    parser.add_argument("--preload", default="", help="Model to preload")
    parser.add_argument("--model", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--voice", default="")
    args = parser.parse_args()

    if sys.platform == "win32":
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")

    if args.server:
        run_server(port=args.port, preload_model=args.preload or args.model)
    else:
        if not args.model or not args.output:
            parser.error("--model and --output are required when not running as --server")
        run_cli(args)


if __name__ == "__main__":
    main()