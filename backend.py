from openai import OpenAI
import json
from translate import Translator
import whisper
from langdetect import detect, DetectorFactory

client = OpenAI(api_key="")

def transcribe_audio(audio_file_path):
    model = whisper.load_model("base") 
    audio = whisper.load_audio(audio_file_path)
    audio = whisper.pad_or_trim(audio)

    transcribed = model.transcribe(audio, language=None)
    return transcribed['text']

def refine_symptom_description(initial_description):
    """
    Asks the GPT model to suggest more accurate descriptions for a patient's symptoms.
    """
    response = client.chat.completions.create(model="gpt-3.5-turbo",
    messages=[
        {"role": "system", "content": "You are a helpful assistant. Given the symptom description: '{initial_description}', "
        "first, identify any vague or unclear part of the description. Then, provide five alternative descriptions "
        "that are more accurate or specific for that part, potentially including medical terminology. "
        "Ensure that the alternatives are closely related to the original description. "
        "If the description is accurate enough without needing refinement, return an empty JSON object. "
        "Format the response in JSON, with the identified vague part under the key 'vague_part',"
        "and the alternatives listed in an array under the key 'alternatives'. If no vague part is identified, "
        "the 'vague_part' key should be set to an empty string."
    }
    ])

    try:
        response_data = json.loads(response.choices[0].message.content.strip())
        if 'alternatives' in response_data and len(response_data['alternatives']) > 0:
            return response_data
        else:
            return {}
    except json.JSONDecodeError:
        return {"error": "Failed to decode response as JSON."}

def translate_text(text, target_language):
    """
    Translates text into the target language using the `translate` library.

    Parameters:
    - text: The text to be translated.
    - target_language: The language you want to translate the text into (e.g., 'es' for Spanish).

    Returns:
    - The translated text or an error message if translation fails.
    """
    print("start")
    translator = Translator(from_lang = "autodetect", to_lang=target_language)
    try:
        translation = translator.translate(text)
        print(translation)
        return translation
    except Exception as e:
        return f"An error occurred: {e}"
    
def detect_language(text):
    """
    Detects the language of the given text.
    
    Parameters:
    - text: A string containing the text whose language is to be detected.

    Returns:
    - A string representing the ISO 639-1 language code (e.g., 'en' for English, 'es' for Spanish, etc.)
    """
    try:
        # Use langdetect's detect function to find the language
        language = detect(text)
        return language
    except Exception as e:
        print(f"Error detecting language: {e}")
        # Default to English if detection fails
        return 'en'