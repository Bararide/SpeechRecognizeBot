from pathlib import Path
import speech_recognition as sr
from pydub import AudioSegment
from pydub.effects import normalize, compress_dynamic_range
import re
from config.celery import celery_app
import language_tool_python

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

def preprocess_audio(audio: AudioSegment) -> AudioSegment:
    """Предобработка аудио перед распознаванием"""
    audio = audio.set_channels(1)
    audio = normalize(audio)
    audio = compress_dynamic_range(audio)
    audio = audio.low_pass_filter(3000)
    
    return audio

def postprocess_text(text: str) -> str:
    """Постобработка распознанного текста"""
    text = re.sub(r"\s+([.,!?])", r"\1", text)
    text = re.sub(r"([.!?])(\s*\w)", lambda m: m.group(1) + " " + m.group(2).upper(), text)

    text = re.sub(r"\s+", " ", text).strip()
    
    return text

def add_punctuation_by_keywords(text):
    punctuation_rules = {
        "что": ", что",
        "когда": ", когда",
        "потому что": ", потому что",
        "если": ", если",
        "хотя": ", хотя",
        "однако": ". Однако",
        "например": ", например",
        "также": ", также",
        "следовательно": ". Следовательно",
        "важно отметить": ". Важно отметить",
    }

    for keyword, replacement in punctuation_rules.items():
        text = text.replace(keyword, replacement)

    if not text.endswith('.'):
        text += '.'

    return text

@celery_app.task(name="tasks.process_media")
def process_media(file_path: str, user_id: int, task_id: str, is_video: bool = False):
    """Обработка медиафайла с улучшенным качеством текста"""
    recognizer = sr.Recognizer()
    temp_files = []
    result_file = RESULTS_DIR / f"{user_id}_{task_id}.txt"
    
    tool = language_tool_python.LanguageTool('ru')

    try:
        if is_video:
            audio_path = Path(file_path).with_suffix(".wav")
            video = AudioSegment.from_file(file_path, format="mp4")
            preprocessed_audio = preprocess_audio(video)
            preprocessed_audio.export(audio_path, format="wav", parameters=["-ar", "16000"])
            temp_files.append(audio_path)
            file_path = audio_path

        audio = AudioSegment.from_file(file_path)
        preprocessed_audio = preprocess_audio(audio)

        wav_path = Path(file_path).with_suffix(".processed.wav")
        preprocessed_audio.export(
            wav_path, 
            format="wav",
            codec="pcm_s16le",
            parameters=["-ar", "16000"]
        )
        temp_files.append(wav_path)

        text_chunks = []
        chunk_length = 60 * 1000
        
        for i, chunk in enumerate(preprocessed_audio[::chunk_length]):
            chunk_path = wav_path.with_stem(f"{wav_path.stem}_chunk{i}")
            chunk.export(chunk_path, format="wav")
            
            with sr.AudioFile(str(chunk_path)) as source:
                audio_data = recognizer.record(source)
                try:
                    text = recognizer.recognize_google(audio_data, language="ru-RU")
                    matches = tool.check(text)
                    corrected_text = language_tool_python.utils.correct(text, matches)
                    text_chunks.append(str(add_punctuation_by_keywords(corrected_text)))
                except sr.UnknownValueError:
                    continue
            
            chunk_path.unlink()

        final_text = postprocess_text(" ".join(text_chunks))
        
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(final_text)

    except Exception as e:
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(f"Ошибка: {str(e)}")
    finally:
        for file in temp_files + [Path(file_path)]:
            if file.exists():
                try:
                    file.unlink()
                except:
                    pass

    return str(result_file)