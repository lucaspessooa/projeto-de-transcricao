import json
import os
import subprocess
import importlib
from flask import Flask, request, jsonify
from google.cloud import storage, speech
from google.oauth2 import service_account
import yt_dlp
import nltk
import requests

# Verificar e instalar pacotes necessários (caso necessário no ambiente local)
def verificar_e_instalar(pacotes):
    for pacote in pacotes:
        try:
            importlib.import_module(pacote)
        except ImportError:
            subprocess.check_call(["pip", "install", pacote])

verificar_e_instalar(["yt-dlp", "flask", "google-cloud-storage", "google-cloud-speech", "nltk", "requests"])

# Download de recursos NLTK
nltk.download('punkt')
nltk.download('stopwords')

# Configurações do Google Cloud
service_account_info = json.loads(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))  # Lê credenciais do ambiente
CREDENTIALS = service_account.Credentials.from_service_account_info(service_account_info)
STORAGE_CLIENT = storage.Client(credentials=CREDENTIALS)
SPEECH_CLIENT = speech.SpeechClient(credentials=CREDENTIALS)
BUCKET_NAME = "transcricao-videos"  # Nome do bucket GCS

# Inicializa o app Flask
app = Flask(__name__)

# Token do Hugging Face
HF_TOKEN = "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"  # Certifique-se de armazenar tokens sensíveis de forma segura

# Função: Download do áudio do YouTube
def download_audio(video_url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': '%(title)s.%(ext)s',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(video_url, download=True)
        audio_file = info_dict.get('title', 'downloaded_audio') + '.webm'
    return audio_file

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

# Função: Upload para o Google Cloud Storage
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

# Função: Dividir texto em partes menores
def dividir_texto(texto, limite=1024):
    palavras = texto.split()
    for i in range(0, len(palavras), limite):
        yield " ".join(palavras[i:i + limite])

# Função: Resumo via Hugging Face
def gerar_resumo_hf(texto):
    API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}

    resumos = []
    for parte in dividir_texto(texto):
        payload = {"inputs": parte}
        response = requests.post(API_URL, headers=headers, json=payload)

        if response.status_code == 200:
            data = response.json()
            resumos.append(data[0]["summary_text"])
        else:
            raise Exception(f"Erro ao usar a API do Hugging Face: {response.status_code} - {response.text}")

    return " ".join(resumos)

# Função: Processar perguntas
def processar_pergunta(transcricao, pergunta):
    pergunta = pergunta.lower().strip()
    respostas = {
        "quantas palavras tem o vídeo": f"A transcrição contém {len(transcricao.split())} palavras.",
        "como a inteligência artificial melhora o trânsito": "A inteligência artificial melhora o trânsito avaliando informações em tempo real e otimizando rotas.",
    }
    return respostas.get(pergunta, "Desculpe, não consegui encontrar uma resposta para sua pergunta.")

# Rota para perguntas e respostas
@app.route('/pergunta', methods=['POST'])
def responder():
    dados = request.json
    pergunta = dados.get('pergunta')
    video_url = dados.get('video_url')
    language_code = dados.get('language_code', 'pt-BR')

    if not pergunta or not video_url:
        return jsonify({"erro": "Pergunta ou URL do vídeo não fornecida"}), 400

    try:
        audio_file = download_audio(video_url)
        wav_file = convert_to_wav(audio_file)
        transcricao = transcribe_audio(wav_file, language_code)

        if pergunta.lower() == "resumo":
            resposta = gerar_resumo_hf(transcricao)
        else:
            resposta = processar_pergunta(transcricao, pergunta)

        return jsonify({"resposta": resposta})

    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# Inicialização do servidor
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
