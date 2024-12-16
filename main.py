import os
import json
import yt_dlp
from flask import Flask, request, jsonify
from google.cloud import storage, speech
from google.oauth2 import service_account
import nltk

# Configurações do Google Cloud
with open("C:\\Users\\LucasPessoa\\Desktop\\projeto\\chaves\\lucas-teste-autenticare-525da8b5645f.json", "r") as f:
    service_account_info = json.load(f)

CREDENTIALS = service_account.Credentials.from_service_account_info(service_account_info)
STORAGE_CLIENT = storage.Client(credentials=CREDENTIALS)
SPEECH_CLIENT = speech.SpeechClient(credentials=CREDENTIALS)
BUCKET_NAME = "transcricao-videos"

# Inicializa o app Flask
app = Flask(__name__)


# Função: Download do áudio do YouTube
def download_audio(video_url):
    # Caminho absoluto para o arquivo cookies.txt
    cookie_file_path = os.path.abspath("cookies.txt")

    # Debugging: Verificar o caminho e a existência do arquivo
    print(f"Path para cookies.txt: {cookie_file_path}")
    print(f"Arquivo cookies.txt existe? {os.path.exists(cookie_file_path)}")

    # Configuração do yt-dlp
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': '%(title)s.%(ext)s',
        'cookiefile': cookie_file_path  # Usar o arquivo cookies.txt
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(video_url, download=True)
            audio_file = info_dict.get('title', 'downloaded_audio') + '.webm'
        return audio_file
    except Exception as e:
        raise Exception(f"Erro ao baixar áudio: {str(e)}")


# Função: Conversão para WAV
def convert_to_wav(input_file, target_rate=16000):
    output_file = input_file.replace('.webm', '.wav')
    command = [
        "ffmpeg", "-i", input_file,
        "-ac", "1",  # Mono
        "-ar", str(target_rate),  # Taxa de amostragem
        output_file
    ]
    subprocess.run(command, check=True)
    return output_file


# Função: Upload para GCS
def upload_to_gcs(bucket_name, source_file, destination_blob):
    bucket = STORAGE_CLIENT.bucket(bucket_name)
    blob = bucket.blob(destination_blob)
    blob.upload_from_filename(source_file)
    return f"gs://{bucket_name}/{destination_blob}"


# Função: Transcrição do áudio
def transcribe_audio(audio_file_path, language_code="pt-BR"):
    gcs_uri = upload_to_gcs(BUCKET_NAME, audio_file_path, os.path.basename(audio_file_path))
    audio = speech.RecognitionAudio(uri=gcs_uri)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code=language_code,
    )
    operation = SPEECH_CLIENT.long_running_recognize(config=config, audio=audio)
    response = operation.result(timeout=300)
    transcript = " ".join(result.alternatives[0].transcript for result in response.results)
    return transcript


# Função: Processar perguntas
def processar_pergunta(transcricao, pergunta):
    pergunta = pergunta.lower().strip()
    if "quantas palavras" in pergunta:
        return f"A transcrição contém {len(transcricao.split())} palavras."
    return "Desculpe, não consegui encontrar uma resposta para sua pergunta."


# Rota para perguntas e respostas
@app.route('/pergunta', methods=['POST'])
def responder():
    dados = request.json
    pergunta = dados.get('pergunta')
    video_url = dados.get('video_url')

    if not pergunta or not video_url:
        return jsonify({"erro": "Pergunta ou URL do vídeo não fornecida"}), 400

    try:
        # Etapa 1: Download do áudio do vídeo
        audio_file = download_audio(video_url)

        # Etapa 2: Conversão do áudio para WAV
        wav_file = convert_to_wav(audio_file)

        # Etapa 3: Transcrição do áudio
        transcricao = transcribe_audio(wav_file)

        # Etapa 4: Processar a pergunta
        resposta = processar_pergunta(transcricao, pergunta)
        return jsonify({"resposta": resposta})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# Inicialização do servidor
if __name__ == '__main__':
    app.run(debug=True)
