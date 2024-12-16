from flask import Flask, request, jsonify
import yt_dlp
import os
from google.cloud import speech
from google.cloud import storage
import base64
import json
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize

# Inicializar o Flask
app = Flask(__name__)

# Baixar dados do NLTK (stopwords e tokenizer)
nltk.download('punkt')
nltk.download('stopwords')

# Configuração de credenciais do Google Cloud
json_credentials = os.environ.get("GOOGLE_CLOUD_CREDENTIALS")
CREDENTIALS = None
try:
    CREDENTIALS = json.loads(base64.b64decode(json_credentials).decode("utf-8"))
except Exception as e:
    raise Exception(f"Erro ao carregar credenciais do Google Cloud: {e}")


# Função para baixar o áudio usando yt-dlp
def download_audio(video_url):
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
            return "audio.wav"  # Retorna o nome do arquivo
    except Exception as e:
        print(f"Erro no download: {e}")
        return None


# Função para fazer upload no Google Cloud Storage
def upload_to_gcs(bucket_name, source_file_name, destination_blob_name):
    client = storage.Client(credentials=CREDENTIALS)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_name)
    print("Arquivo enviado para o GCS.")


# Função de transcrição do Google Cloud Speech-to-Text
def transcribe_audio(file_path):
    client = speech.SpeechClient(credentials=CREDENTIALS)
    with open(file_path, "rb") as audio_file:
        content = audio_file.read()
    audio = speech.RecognitionAudio(content=content)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        language_code="pt-BR"
    )
    response = client.recognize(config=config, audio=audio)
    transcriptions = " ".join([result.alternatives[0].transcript for result in response.results])
    return transcriptions


# Rota para receber a URL do vídeo e responder perguntas
@app.route('/pergunta', methods=['POST'])
def process_video():
    try:
        data = request.get_json()
        video_url = data.get("url")
        pergunta = data.get("pergunta")

        # Baixar áudio
        audio_path = download_audio(video_url)
        if not audio_path:
            return jsonify({"error": "Falha ao baixar o vídeo"}), 500

        # Fazer upload para GCS
        bucket_name = "transcricao-videos"
        upload_to_gcs(bucket_name, audio_path, "audio.wav")

        # Transcrever áudio
        transcricao = transcribe_audio(audio_path)

        # Processar pergunta e filtrar resposta (exemplo simples)
        palavras = word_tokenize(transcricao, language='portuguese')
        palavras_filtradas = [word for word in palavras if word.lower() not in stopwords.words('portuguese')]
        resposta = " ".join(palavras_filtradas[:50])  # Simplesmente retorna parte do texto

        return jsonify({
            "transcricao": transcricao,
            "resposta": f"Resposta baseada na pergunta '{pergunta}': {resposta}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
