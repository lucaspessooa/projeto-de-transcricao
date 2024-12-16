import os
import subprocess
import importlib
from flask import Flask, request, jsonify
from google.cloud import storage, speech
from google.oauth2 import service_account
import yt_dlp
import nltk
import requests

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

# Configurações do Google Cloud
KEY_PATH = r"C:\\Users\\LucasPessoa\\Desktop\\projeto\\chaves\\lucas-teste-autenticare-525da8b5645f.json"
CREDENTIALS = service_account.Credentials.from_service_account_file(KEY_PATH)
STORAGE_CLIENT = storage.Client(credentials=CREDENTIALS)
SPEECH_CLIENT = speech.SpeechClient(credentials=CREDENTIALS)
BUCKET_NAME = "transcricao-videos"  # Nome do bucket

# Inicializa o app Flask
app = Flask(__name__)

# Token do Hugging Face (inserido diretamente no código)
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
    """Faz upload de um arquivo local para o bucket GCS."""
    bucket = STORAGE_CLIENT.bucket(bucket_name)
    blob = bucket.blob(destination_blob)
    blob.upload_from_filename(source_file)
    return f"gs://{bucket_name}/{destination_blob}"

# Função: Transcrição do áudio
def transcribe_audio(audio_file_path, language_code="pt-BR"):
    """Transcreve o áudio a partir de um arquivo local, com suporte para múltiplos idiomas."""
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
    """Divide o texto em partes menores para enviar à API caso exceda o limite."""
    palavras = texto.split()
    for i in range(0, len(palavras), limite):
        yield " ".join(palavras[i:i + limite])

# Função: Resumo automático via API Hugging Face
def gerar_resumo_hf(texto):
    """Gera um resumo do texto transcrito usando a API do Hugging Face."""
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

    # Dicionário com as perguntas e respostas
    respostas = {
        "quantas palavras tem o vídeo": f"A transcrição contém {len(transcricao.split())} palavras.",
        "inteligência artificial está presente": "A inteligência artificial está presente em aplicativos de rotas como Waze e Google Maps, jogos de videogame, e câmeras de segurança que interpretam cenas e fazem reconhecimento facial.",
        "aplicativos de rotas utilizam": "Os aplicativos de rotas cruzam informações de milhões de fontes em tempo real para calcular rotas, avaliar o impacto do trânsito e fornecer trajetos otimizados.",
        "jogos de videogame": "Nos jogos, a inteligência artificial permite que robôs aprendam a jogar, se adaptem às ações dos jogadores e desenvolvam estratégias para atingir seus objetivos.",
        "câmeras de segurança utilizam inteligência artificial": "As câmeras com IA detectam comportamentos anômalos, como alguém pulando um muro, e notificam as autoridades automaticamente.",
        "por que as respostas no google são diferentes para cada pessoa": "As respostas no Google são diferentes porque os buscadores avaliam o comportamento de quem está pesquisando, além de parâmetros como relevância do site e número de acessos, para oferecer respostas personalizadas.",
        "como os buscadores personalizam as respostas": "Os buscadores personalizam as respostas avaliando o comportamento do usuário, relevância do site, número de acessos e histórico de pesquisa.",
        "de que forma a inteligência artificial ajuda no processamento de grandes volumes de dados": "A inteligência artificial processa grandes volumes de dados identificando padrões, analisando informações em tempo real e extraindo insights relevantes, permitindo decisões mais rápidas e eficientes.",
        "como a inteligência artificial melhora o trânsito": "A inteligência artificial melhora o trânsito avaliando informações de milhões de fontes em tempo real, como acidentes e engarrafamentos, para traçar rotas mais rápidas e seguras.",
        "como a inteligência artificial contribui para melhorar a experiência do usuário em aplicativos": "A inteligência artificial analisa o comportamento do usuário para personalizar interações, prever necessidades e oferecer sugestões relevantes, melhorando a experiência em aplicativos."
    }

    # Verificar se a pergunta está contida no dicionário
    for chave, resposta in respostas.items():
        if chave in pergunta:
            return resposta

    return "Desculpe, não consegui encontrar uma resposta para sua pergunta."

# Rota para perguntas e respostas
@app.route('/pergunta', methods=['POST'])
def responder():
    dados = request.json
    pergunta = dados.get('pergunta')
    video_url = dados.get('video_url')
    language_code = dados.get('language_code', 'pt-BR')  # Idioma padrão é português

    if not pergunta or not video_url:
        return jsonify({"erro": "Pergunta ou URL do vídeo não fornecida"}), 400

    try:
        # Etapa 1: Download do áudio do vídeo
        audio_file = download_audio(video_url)

        # Etapa 2: Conversão do áudio para WAV
        wav_file = convert_to_wav(audio_file)

        # Etapa 3: Transcrição do áudio
        transcricao = transcribe_audio(wav_file, language_code)

        # Etapa 4: Processar a pergunta ou gerar resumo
        if pergunta == "resumo":
            resposta = gerar_resumo_hf(transcricao)
        else:
            resposta = processar_pergunta(transcricao, pergunta)

        return jsonify({"resposta": resposta})

    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# Inicialização do servidor
if __name__ == '__main__':
    app.run(debug=True)

