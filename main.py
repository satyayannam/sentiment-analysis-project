from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_file, send_from_directory
import os
import subprocess
from google.cloud import speech, texttospeech, language_v1
import io
import wave

app = Flask(__name__)

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'wav'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the uploads and TTS folders exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs('tts', exist_ok=True)

@app.route('/tts/<filename>')
def serve_tts_file(filename):
    return send_from_directory('tts', filename)

# Synthesize text to speech using Google Cloud Text-to-Speech
def synthesize_text(text, output_path):
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
    )
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)

    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    with open(output_path, "wb") as out:
        out.write(response.audio_content)


# Check if the file is allowed
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Convert audio to LINEAR16 with 16kHz
def convert_to_16000hz(input_path, output_path):
    try:
        subprocess.run(
            ['ffmpeg', '-i', input_path, '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', output_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True  # Add shell=True to ensure Windows compatibility
        )
        print(f"Converted {input_path} to {output_path} with 16000 Hz sample rate")
        return output_path
    except Exception as e:
        print(f"Error during conversion: {e}")
        return None

@app.route('/sentiment/<filename>')
def sentiment_file(filename):
    return send_from_directory('sentiments', filename)


# Fetch files for display
def get_files():
    files = []
    for filename in os.listdir(UPLOAD_FOLDER):
        if allowed_file(filename) or filename.endswith('.txt'):
            files.append(filename)
    print("Available files:", files)  # Debugging
    return sorted(files, reverse=True)


@app.route('/')
def index():
    files = get_files()  # List of uploaded audio files (from uploads folder)
    tts_files = [f for f in os.listdir('tts') if f.endswith('.mp3')]  # Fetch TTS files
    
    # Get list of TTS sentiment files
    tts_sentiments = {}
    for filename in os.listdir('sentiments'):
        if filename.startswith('tts_sentiment_'):
            # Extract the original mp3 filename from the sentiment filename
            mp3_filename = filename.replace('tts_sentiment_', '').replace('.txt', '.mp3')
            if mp3_filename in tts_files:
                tts_sentiments[mp3_filename] = filename
    
    return render_template('index.html', files=files, tts_files=tts_files, tts_sentiments=tts_sentiments)

@app.route('/upload', methods=['POST'])
def upload_audio():
    if 'audio_data' not in request.files:
        print("No audio data in request")
        return "No audio data in request", 400

    file = request.files['audio_data']
    if file.filename == '':
        print("No file selected")
        return "No file selected", 400

    # Save the uploaded audio file with a unique name
    filename = datetime.now().strftime("%Y%m%d-%I%M%S%p") + '.wav'
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)
    print(f"Saved file: {file_path}")

    # Convert the audio to 16kHz
    converted_file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"converted_{filename}")
    convert_to_16000hz(file_path, converted_file_path)

    # Delete the original file to avoid duplicates
    os.remove(file_path)
    print(f"Deleted original file: {file_path}")

    # Transcribe the converted audio
    try:
        transcript = transcribe_audio(converted_file_path)
        if transcript:
            print(f"Transcription result: {transcript}")
        else:
            print("No transcription results")
    except Exception as e:
        print(f"Error during transcription: {e}")
        return f"Error during transcription: {e}", 500

    # Analyze sentiment of the transcription
    sentiment_label, score, magnitude = analyze_sentiment(transcript)

    # Save the sentiment result in a file
    sentiment_filename = save_sentiment_result(transcript, sentiment_label, score, magnitude, filename)

    return redirect(f"/download_sentiment/{sentiment_filename}")


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Transcribe audio using Google Cloud Speech-to-Text
def transcribe_audio(file_path):
    try:
        client = speech.SpeechClient()

        # Read the audio file
        with io.open(file_path, 'rb') as audio_file:
            content = audio_file.read()

        # Configure the request
        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code='en-US',  # Set the language for transcription
        )

        # Perform transcription
        response = client.recognize(config=config, audio=audio)

        if response.results:
            # Combine all transcriptions into a single text
            transcript = "\n".join(result.alternatives[0].transcript for result in response.results)
            print(f"Transcription successful: {transcript}")

            # Save the transcription to a text file
            text_file_path = os.path.splitext(file_path)[0] + ".txt"
            with open(text_file_path, 'w') as text_file:
                text_file.write(transcript)

            print(f"Transcription saved to: {text_file_path}")
            return transcript  # Return the transcript for further use

        else:
            print("No transcription results")
            return None

    except Exception as e:
        print(f"Error in transcription: {e}")
        return None


# Analyze sentiment using Google Cloud Natural Language API
def analyze_sentiment(text):
    client = language_v1.LanguageServiceClient()

    # Prepare the document
    document = language_v1.Document(
        content=text,
        type_=language_v1.Document.Type.PLAIN_TEXT,
    )

    # Perform sentiment analysis
    sentiment = client.analyze_sentiment(document=document).document_sentiment

    # Sentiment score (ranges from -1.0 to 1.0)
    score = sentiment.score
    magnitude = sentiment.magnitude

    # Determine if the sentiment is positive, negative, or neutral
    if score > 0.25:
        sentiment_label = "Positive"
    elif score < -0.25:
        sentiment_label = "Negative"
    else:
        sentiment_label = "Neutral"

    print(f"Sentiment score: {score}, Magnitude: {magnitude}")
    print(f"Sentiment label: {sentiment_label}")

    return sentiment_label, score, magnitude


# Ensure sentiments folder exists
os.makedirs('sentiments', exist_ok=True)

def save_sentiment_result(text, sentiment_label, score, magnitude, original_filename=None):
    # Create a filename for the sentiment result
    sentiment_filename = f"sentiment_converted_{os.path.splitext(original_filename)[0]}.txt" if original_filename else "sentiment_results.txt"
    
    # Define the path inside the sentiments folder
    sentiment_path = os.path.join('sentiments', sentiment_filename)

    # Save the sentiment analysis result to the file
    with open(sentiment_path, 'w') as f:
        f.write(f"Original Text:\n{text}\n\n")
        f.write(f"Sentiment: {sentiment_label}\n")
        f.write(f"Sentiment Score: {score}\n")
        f.write(f"Sentiment Magnitude: {magnitude}\n")
        if original_filename:
            f.write(f"Linked to audio file: {original_filename}\n")

    print(f"Sentiment result saved as {sentiment_path}")
    return sentiment_filename  # Return filename only




@app.route('/sentiments/<filename>')
def download_sentiment(filename):
    return send_from_directory('sentiments', filename)




@app.route('/upload_text', methods=['POST'])
def upload_text():
    text = request.form['text']
    if not text.strip():
        print("No text provided")
        return redirect('/')

    # Save the generated audio to the 'tts' directory
    tts_folder = 'tts'
    os.makedirs(tts_folder, exist_ok=True)
    filename = datetime.now().strftime("%Y%m%d-%I%M%S%p") + '.mp3'
    output_path = os.path.join(tts_folder, filename)

    try:
        # Generate the audio
        synthesize_text(text, output_path)
        
        # Analyze sentiment of the provided text
        sentiment_label, score, magnitude = analyze_sentiment(text)
        
        # Save sentiment result for TTS with a special prefix to identify it
        sentiment_filename = f"tts_sentiment_{filename.replace('.mp3', '.txt')}"
        sentiment_path = os.path.join('sentiments', sentiment_filename)
        
        with open(sentiment_path, 'w') as f:
            f.write(f"Original Text:\n{text}\n\n")
            f.write(f"Sentiment: {sentiment_label}\n")
            f.write(f"Sentiment Score: {score}\n")
            f.write(f"Sentiment Magnitude: {magnitude}\n")
            f.write(f"Linked to TTS audio file: {filename}\n")
        
        print(f"TTS Sentiment result saved as {sentiment_path}")
        
    except Exception as e:
        print(f"Error generating audio or analyzing sentiment: {e}")
        return f"Error generating audio or analyzing sentiment: {e}", 500

    print(f"Generated audio saved as {filename}")
    return redirect('/')

@app.route('/analyze_tts_sentiment', methods=['POST'])
def analyze_tts_sentiment():
    text = request.form['text']
    if not text.strip():
        print("No text provided")
        return redirect('/')

    # Analyze sentiment of the provided text
    sentiment_label, score, magnitude = analyze_sentiment(text)

    # Save sentiment result with a temporary name
    sentiment_filename = f"tts_sentiment_temp_{datetime.now().strftime('%Y%m%d-%I%M%S%p')}.txt"
    sentiment_path = os.path.join('sentiments', sentiment_filename)
    
    with open(sentiment_path, 'w') as f:
        f.write(f"Original Text:\n{text}\n\n")
        f.write(f"Sentiment: {sentiment_label}\n")
        f.write(f"Sentiment Score: {score}\n")
        f.write(f"Sentiment Magnitude: {magnitude}\n")

    return redirect(f"/download_sentiment/{sentiment_filename}")


@app.route('/script.js', methods=['GET'])
def scripts_js():
    return send_file('./script.js')


if __name__ == '__main__':
    app.run(debug=True)