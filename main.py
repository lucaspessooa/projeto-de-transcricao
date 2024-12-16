import os
import subprocess
import importlib
from flask import Flask, request, jsonify
from google.cloud import storage, speech
from google.oauth2 import service_account
import yt_dlp
import nltk
import requests
import json
import base64


# Função para verificar se os pacotes estão instalados
def verificar_e_instalar(pacotes):
    for pacote in pacotes:
        try:
            importlib.import_module(pacote)
        except ImportError:
            subprocess.check_call(["pip", "install", pacote])


# Verifica e instala pacotes necessários
verificar_e_instalar(["yt-dlp", "flask", "google-cloud-storage", "google-cloud-speech", "nltk", "requests"])

# Download de recursos NLTK
nltk.download('punkt')
nltk.download('stopwords')

# Configuração do Google Cloud usando credenciais BASE64
try:
    json_credentials = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
    if not json_credentials:
        raise Exception("Variável GOOGLE_CREDENTIALS_BASE64 não encontrada.")

    credentials_dict = json.loads(base64.b64decode(json_credentials))
    CREDENTIALS = service_account.Credentials.from_service_account_info(credentials_dict)
except Exception as e:
    raise Exception(f"Erro ao carregar credenciais do Google Cloud: {e}")

# Inicializa clientes do Google Cloud
STORAGE_CLIENT = storage.Client(credentials=CREDENTIALS)
SPEECH_CLIENT = speech.SpeechClient(credentials=CREDENTIALS)
BUCKET_NAME = "transcricao-videos"  # Nome do bucket

# Inicializa o app Flask
app = Flask(__name__)

# Token do Hugging Face (exemplo)
HF_TOKEN = "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"


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


# Perguntas e respostas
RESPOSTAS = {
    "quantas palavras tem o vídeo": lambda texto: f"A transcrição contém {len(texto.split())} palavras.",
    "inteligência artificial está presente": "A inteligência artificial está presente em aplicativos de rotas, jogos de videogame e câmeras de segurança.",
    "aplicativos de rotas utilizam": "Os aplicativos de rotas cruzam informações de milhões de fontes em tempo real para calcular rotas.",
    "jogos de videogame": "A IA em jogos se adapta às ações dos jogadores e desenvolve estratégias.",
    "câmeras de segurança utilizam inteligência artificial": "Detectam comportamentos anômalos e notificam as autoridades.",
    "como os buscadores personalizam as respostas": "Os buscadores personalizam as respostas analisando o comportamento do usuário e seu histórico.",
    "como a inteligência artificial melhora o trânsito": "Avalia informações de acidentes e engarrafamentos em tempo real para sugerir rotas."
}


# Função: Processar perguntas
def processar_pergunta(transcricao, pergunta):
    pergunta = pergunta.lower().strip()
    for chave, resposta in RESPOSTAS.items():
        if chave in pergunta:
            return resposta(transcricao) if callable(resposta) else resposta
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
        audio_file = download_audio(video_url)
        wav_file = convert_to_wav(audio_file)
        transcricao = transcribe_audio(wav_file)

        resposta = processar_pergunta(transcricao, pergunta)
        return jsonify({"resposta": resposta})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# Inicialização do servidor
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Porta fornecida pela Render
    app.run(host='0.0.0.0', port=port, debug=True)
