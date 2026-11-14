# Safety net: no engine test may push a real ntfy/Telegram alert to the owner's phone.
import engine.alerts

engine.alerts._send = lambda title, message: {"success": False, "message": f"alerts disabled in tests ({title})"}
