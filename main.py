import os
import tempfile
import logging
from flask import Flask, request, abort
import telegram
from openai import OpenAI   # ✅ Nuevo import de la API moderna
from gtts import gTTS

# --- Configuración básica ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")  # opcional

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("Faltan variables de entorno TELEGRAM_TOKEN o OPENAI_API_KEY.")

# ✅ Ahora se instancia un cliente OpenAI con la API key
client = OpenAI(api_key=OPENAI_API_KEY)
bot = telegram.Bot(token=TELEGRAM_TOKEN)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


# --- Helpers ---
def chatgpt_reply(prompt, model="gpt-4o-mini", max_tokens=600):
    """Enviar prompt a OpenAI Chat Completions y retornar texto respuesta."""
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.7,
        )
        text = resp.choices[0].message.content.strip()
        return text
    except Exception as e:
        logging.exception("Error llamando a OpenAI ChatCompletion")
        return "Lo siento, ocurrió un error al procesar la respuesta."


def generate_image(prompt, size="1024x1024"):
    """Generar imagen con DALL·E usando la API moderna."""
    try:
        img_resp = client.images.generate(
            model="gpt-image-1",  # ✅ Modelo actual de generación de imágenes
            prompt=prompt,
            size=size,
            n=1
        )
        # ✅ Ahora la respuesta trae una lista con URLs o base64
        url = img_resp.data[0].url or img_resp.data[0].b64_json
        return url
    except Exception:
        logging.exception("Error generando imagen")
        return None


def text_to_speech_save(text, lang="es"):
    """Genera un mp3 con gTTS y devuelve la ruta del archivo temporal."""
    try:
        tts = gTTS(text=text, lang=lang)
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        tts.save(path)
        return path
    except Exception:
        logging.exception("Error TTS")
        return None


# --- Rutas ---
@app.route("/", methods=["GET"])
def index():
    return "Bot Telegram - Webhook activo."


@app.route(f"/webhook", methods=["POST"])
def webhook_no_secret():
    if WEBHOOK_SECRET:
        abort(404)
    return handle_update(request.get_json(force=True))


@app.route(f"/webhook/<secret>", methods=["POST"])
def webhook_with_secret(secret):
    if not WEBHOOK_SECRET or secret != WEBHOOK_SECRET:
        logging.warning("Webhook recibido con secreto inválido.")
        abort(403)
    return handle_update(request.get_json(force=True))


def handle_update(update_json):
    try:
        update = telegram.Update.de_json(update_json, bot)
    except Exception:
        logging.exception("JSON inválido para telegram.Update")
        return "OK"

    message = update.message
    if not message:
        return "OK"

    chat_id = message.chat.id
    text = message.text or ""
    user = message.from_user.username if message.from_user else str(message.from_user)

    logging.info("Mensaje de %s en chat %s: %s", user, chat_id, text)

    if text.startswith("/start") or text.startswith("/help"):
        help_text = (
            "Hola! Soy tu bot IA.\n\n"
            "Comandos:\n"
            "/start /help - Mostrar ayuda\n"
            "/imagen <texto> - Generar imagen con IA\n"
            "/voz <texto> - Generar audio (mp3) con TTS\n\n"
            "Si escribes cualquier otra cosa, responderé usando ChatGPT."
        )
        bot.send_message(chat_id=chat_id, text=help_text)
        return "OK"

    if text.startswith("/imagen"):
        prompt = text.partition(" ")[2].strip()
        if not prompt:
            bot.send_message(chat_id=chat_id, text="Usa: /imagen <descripción de la imagen>")
            return "OK"
        bot.send_message(chat_id=chat_id, text="Generando imagen... ⏳")
        url_or_b64 = generate_image(prompt)
        if not url_or_b64:
            bot.send_message(chat_id=chat_id, text="No pude generar la imagen. Intenta de nuevo más tarde.")
            return "OK"

        if url_or_b64.startswith("http"):
            bot.send_photo(chat_id=chat_id, photo=url_or_b64, caption=f"Imagen: {prompt}")
            return "OK"
        else:
            import base64
            data = base64.b64decode(url_or_b64)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp.write(data)
            tmp.flush()
            tmp.close()
            with open(tmp.name, "rb") as f:
                bot.send_photo(chat_id=chat_id, photo=f, caption=f"Imagen: {prompt}")
            os.unlink(tmp.name)
            return "OK"

    if text.startswith("/voz") or text.startswith("/tts"):
        prompt = text.partition(" ")[2].strip()
        if not prompt:
            bot.send_message(chat_id=chat_id, text="Usa: /voz <texto a convertir en audio>")
            return "OK"
        bot.send_message(chat_id=chat_id, text="Generando audio... ⏳")
        path = text_to_speech_save(prompt, lang="es")
        if not path:
            bot.send_message(chat_id=chat_id, text="No pude generar el audio. Intenta luego.")
            return "OK"
        with open(path, "rb") as audio_file:
            bot.send_audio(chat_id=chat_id, audio=audio_file, timeout=120)
        os.unlink(path)
        return "OK"

    bot.send_chat_action(chat_id=chat_id, action=telegram.ChatAction.TYPING)
    reply = chatgpt_reply(text)
    bot.send_message(chat_id=chat_id, text=reply)
    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
    
# --- Punto de entrada para ejecutar localmente (útil en pruebas) ---
if __name__ == "__main__":
    # En producción Render usará gunicorn que apunta a main:app
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
