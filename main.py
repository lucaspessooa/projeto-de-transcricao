import os
import base64
import json
from flask import Flask, request, jsonify
from google.cloud import speech
from google.cloud import storage
import yt_dlp
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize

# Baixar dados do NLTK
nltk.download('punkt')
nltk.download('stopwords')

# Configurar credenciais do Google Cloud
json_credentials = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
if not json_credentials:
    raise Exception("Variável GOOGLE_CREDENTIALS_BASE64 não foi configurada corretamente.")

CREDENTIALS = json.loads(base64.b64decode(json_credentials).decode("utf-8"))

# Inicializar Flask
app = Flask(__name__)

# Configurações do Google Cloud
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_credentials.json"
with open("google_credentials.json", "w") as file:
    json.dump(CREDENTIALS, file)


def download_audio(video_url):
    """Download do áudio do vídeo usando yt-dlp com cookies."""
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav', 'preferredquality': '192'}],
        'outtmpl': 'audio.%(ext)s',
        'cookiefile': 'cookies',  # Caminho para o arquivo de cookies
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
            print("Download concluído com sucesso!")
    except Exception as e:
        print(f"Erro no download: {e}")
        raise


def upload_to_gcs(bucket_name, file_name):
    """Upload do arquivo para o Google Cloud Storage."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(file_name)
    blob.upload_from_filename(file_name)
    print(f"Arquivo {file_name} enviado para o bucket {bucket_name}.")


def transcribe_audio(gcs_uri):
    """Transcrição do áudio usando Google Cloud Speech-to-Text."""
    client = speech.SpeechClient()
    audio = speech.RecognitionAudio(uri=gcs_uri)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        language_code="pt-BR"
    )
    response = client.recognize(config=config, audio=audio)
    text = " ".join(result.alternatives[0].transcript for result in response.results)
    return text


@app.route('/pergunta', methods=['POST'])
def handle_question():
    """Endpoint para processar o download, transcrição e responder perguntas."""
    try:
        data = request.get_json()
        video_url = data.get("video_url")
        bucket_name = "transcricao-videos"

        if not video_url:
            return jsonify({"error": "A URL do vídeo é obrigatória."}), 400

        # Download do áudio
        download_audio(video_url)

        # Upload do áudio para o Google Cloud Storage
        upload_to_gcs(bucket_name, "audio.wav")

        # Transcrição do áudio
        gcs_uri = f"gs://{bucket_name}/audio.wav"
        transcribed_text = transcribe_audio(gcs_uri)

        # Processamento simples da transcrição
        stop_words = set(stopwords.words('portuguese'))
        words = word_tokenize(transcribed_text)
        filtered_words = [word for word in words if word.lower() not in stop_words]

        return jsonify({
            "transcription": transcribed_text,
            "filtered_words": filtered_words
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=10000)
