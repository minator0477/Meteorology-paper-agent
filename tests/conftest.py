import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# score.py / report.py はインポート時に環境変数を必須で読むので、
# テスト実行時はダミー値を注入しておく（実際の API/Webhook には一切アクセスしない）。
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-key-for-tests")
os.environ.setdefault("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/000000/dummy")
