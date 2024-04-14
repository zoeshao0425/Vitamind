from flask import Flask, request, render_template
from flask_login import current_user
from translate import Translator
from flask import session
import os
import openai
from flask import jsonify
import json
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, logout_user
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask import flash
from langdetect import detect
from flask_migrate import Migrate
import logging
from sqlalchemy import MetaData, Table
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.exc import OperationalError, ProgrammingError
import os
import time
from backend import transcribe_audio, refine_symptom_description, translate_text, detect_language
from werkzeug.utils import secure_filename

app = Flask(__name__, static_url_path='/static')
app.secret_key = 'adminZoe'

DATABASE_URL="postgresql://llzddejsxniamp:40e4080a32886f9180ee7d006e42cbcefc19d12b3164948c2f496c460d6d4b4b@ec2-54-211-177-159.compute-1.amazonaws.com:5432/d4ek6m8kums9q3"
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL

db = SQLAlchemy(app)
migrate = Migrate(app, db)

openai.api_key = ""

app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['ALLOWED_EXTENSIONS'] = {'wav', 'mp3', 'ogg', 'm4a'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

TEMPERATURE = 0.5
MAX_TOKENS = 800
FREQUENCY_PENALTY = 0
PRESENCE_PENALTY = 0.6
# limits how many questions we include in the prompt
MAX_CONTEXT_QUESTIONS = 10

USER_LANGUAGE=""
USER_LEVEL=""
USER_TOPIC=""
USER_LENGTH=0
PREVIOUS=[]

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120))
    content = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    user = db.relationship('User', backref=db.backref('articles', lazy=True))

class WordList(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(120))
    translation = db.Column(db.String(120))  # new translation attribute
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    user = db.relationship('User', backref=db.backref('word_lists', lazy=True))

class LanguageDifficulty(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(20))
    language = db.Column(db.String(50))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    user = db.relationship('User', backref=db.backref('language_difficulties', lazy=True))

metadata = MetaData()

with app.app_context():
    try:
        # Try to query one of your tables, if it doesn't exist, it will raise an OperationalError
        User.query.first()
    except (ProgrammingError, OperationalError):
        # Create tables
        db.create_all()

login_manager = LoginManager()
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_user_articles(user_id):
    articles = Article.query.filter_by(user_id=user_id).all()
    return articles

def get_user_word_list(user_id):
    word_list = WordList.query.filter_by(user_id=user_id).all()
    return word_list

def get_user_language_difficulties(user_id):
    difficulties = LanguageDifficulty.query.filter_by(user_id=user_id).all()
    return difficulties

@app.route('/upload-audio', methods=['POST'])
def upload_audio():
    if 'audio' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['audio']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    # Transcribe the audio
    try:
        transcript = transcribe_audio(file_path)
        return jsonify({'transcript': transcript})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/process-input', methods=['POST'])
def process_input():
    if 'audio_file' in request.files:
        file = request.files['audio_file']
        filename = file.filename
        audio_path = os.path.join('/path/to/save', filename)
        file.save(audio_path)
        transcript = transcribe_audio(audio_path)
        translated_text = translate_text(transcript, 'en')
    elif 'text_input' in request.json:
        translated_text = translate_text(request.json['text_input'], 'en')
    else:
        return jsonify({"error": "No valid input provided"}), 400
    
    refined_data = refine_symptom_description(translated_text)
    return jsonify({
        'original': translated_text,
        'refined': refined_data
    })
    
@app.route('/refine-symptom-description', methods=['POST'])
def handle_refinement():
    data = request.get_json()
    initial_description = data['initial_description']
    logging.info(f"Received description: {initial_description}")
    translated_to_english = translate_text(initial_description, 'en')
    
    refined_data = refine_symptom_description(translated_to_english)
    logging.info(f"Refined data: {refined_data}")
    
    if refined_data and 'alternatives' in refined_data:
        alternatives_text = "\n".join([f"{i+1}. {alt}" for i, alt in enumerate(refined_data['alternatives'])])
        response_text = (f"Your descriptions seem not clear enough, you may consider rephrasing it as:\n"
                         f"{alternatives_text}\n"
                         f"6. Keep the original: {initial_description}")
        lang = detect_language(initial_description)
        
        session['user_language'] = lang
        
        response_org_text = translate_text(response_text, lang)
        refined_data['formatted_alternatives'] = response_text
        refined_data['formatted_org_alternatives'] = response_org_text
    
    return jsonify(refined_data)

@app.route('/api/user-language')
def get_user_language():
    return jsonify(user_language=session.get('user_language', 'en'))

@app.route('/translate', methods=['POST'])
def translate_route():
    # Retrieve data from POST request
    data = request.get_json()
    text = data.get('text')
    target_language = data.get('target_language')
    
    print(text, target_language)

    # Call the translate_text function
    translation_result = translate_text(text, target_language)
    print(translation_result)

    # Check if the result is a string (successful translation) or an error message
    if isinstance(translation_result, str):
        return jsonify({'translatedText': translation_result})
    else:
        return jsonify({'error': translation_result}), 500
    
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
    return render_template("login.html")

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('/'))  # changed '/' to 'index'

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user:
            flash('Username already exists. Choose a different one.')
            return redirect(url_for('register'))
        new_user = User(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('index'))
    return render_template("register.html")

@app.route('/profile', methods=['GET'])
@login_required
def profile():
    articles = get_user_articles(current_user.id)
    word_list = get_user_word_list(current_user.id)
    language_difficulties = get_user_language_difficulties(current_user.id)
    return render_template(
        'profile.html',
        user=current_user,
        articles=articles,
        word_list=word_list,
        language_difficulties=language_difficulties
    )

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Your POST handling logic here
        pass
    return render_template("index.html")

def detect_language(text):
    try:
        language = detect(text)
        return language
    except:
        return "Unknown"

@app.route('/paraphrase', methods=['GET', 'POST'])
def paraphrase():
    if request.method == 'POST':
        # Assuming you're receiving the text to be paraphrased in a form input with the name 'article_text'
        article_text = request.form['article_text']
        # Assuming you're receiving the difficulty option in a form input with the name 'difficulty_option'
        difficulty_option = request.form['difficulty_option']

        # Call the 'paraphrase_text' function with the provided article_text and difficulty_option and get the result
        paraphrased_text = paraphrase_text(article_text, difficulty_option)

        # Then you could pass the result to the template.
        return render_template('paraphrase.html', result=paraphrased_text)

    else:
        # If the method is GET, just display the page.
        return render_template('paraphrase.html')

@app.route('/entry', methods=['GET', 'POST'])
def entry():
    if request.method == 'POST':
        # Your POST handling logic here
        pass
    return render_template("entry.html")

def translator(text, language):
    language_codes = {
        "Simplified Chinese": 'zh',
        "zh-cn": 'zh',
        "Spanish": 'es',
        "German": 'de',
        "French": 'fr',
        "Italian": 'it'
    }

    # Get the language code
    code = language_codes.get(language)

    # Handle case where language is not in the list
    if code is None:
        return "Unsupported language"

    # Translate the text
    translator = Translator(from_lang=code, to_lang='en')
    translation = translator.translate(text)
    print(translation)
    return translation

@app.route('/about')
def about():
    return render_template('about.html')


def generate_article_and_quiz(previous_questions_and_answers, language, level, topic, length):
    """Get a response from ChatCompletion
    Args:
        
        previous_questions_and_answers: Chat history
        new_question: The new question to ask the bot
    Returns:
        The response text
    """
    print(level)
    if level==0: 
        instruction = f"Please generate a similar article in {language} on {topic} but with decreased complexity. The length of sentences should be decreased by 10%, and the words should be replaced by more frequent words."
    elif level==7: 
        instruction = f"Please generate a similar article in {language} on {topic} but with increased complexity. The length of sentences should be increased by 10%, and the words should be replaced by less frequent words."
    else: 
        global USER_LANGUAGE
        global USER_LEVEL
        global USER_TOPIC
        global USER_LENGTH

        # start by storing user input
        USER_LANGUAGE=language
        USER_LEVEL=level
        USER_TOPIC=topic
        USER_LENGTH=length

        dict={"HSK1/A1":1,"HSK2/A2":2, "HSK3/B1":3, "HSK4/B2":4, "HSK5/C1":5, "HSK6/C2":6}
        euro_dict={1:"A1", 2:"A2", 3:"B1", 4:"B2", 5:"C1", 6:"C2"}
        if language == "Simplified Chinese":
            input_level=f"HSK level {dict[level]}"
        else:
            num=dict[level]
            input_level=f"{euro_dict[num]}"
        # build the messages
        instruction = f"Generate an interesting news article in {language} on {topic} for a non native speaker with level {input_level} with length of {length} words. Do not give an intro. Do not simply give an encyclopedic description."
        print(instruction)
    messages = [
        { "role": "system", "content": instruction },
    ]
    
    # add the previous questions and answers
    for question, answer in previous_questions_and_answers[-MAX_CONTEXT_QUESTIONS:]:
        messages.append({ "role": "user", "content": question })
        messages.append({ "role": "assistant", "content": answer })
    # add the new question
    # messages.append({ "role": "user", "content": new_question })

    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        top_p=1,
        frequency_penalty=FREQUENCY_PENALTY,
        presence_penalty=PRESENCE_PENALTY,
    )

    PREVIOUS.append((instruction, completion.choices[0].message.content))
    
    article_content = completion.choices[0].message.content

    # Save the generated article and difficulty level to the database
    # This assumes that you have access to the current user's id
    if current_user.is_authenticated:
        new_article = Article(title=topic, content=article_content, user_id=current_user.id)
        db.session.add(new_article)
    
        new_difficulty = LanguageDifficulty(level=level, language=language, user_id=current_user.id)
        db.session.add(new_difficulty)
    
        db.session.commit()
        
    session['quiz_data'] = take_quiz()

    return article_content, session['quiz_data']

def get_key(val, dict):
    for key, value in dict.items():
        if val == value:
            return key

def redo(option): 
    global USER_LEVEL

    dict={"HSK1/A1":1,"HSK2/A2":2, "HSK3/B1":3, "HSK4/B2":4, "HSK5/C1":5, "HSK6/C2":6}
    level_num=dict[USER_LEVEL]
    # level_str=get_key(level_num,dict)
    if option == "too easy": 
        level_num+=1
        if level_num==7: 
            result, quiz =generate_article_and_quiz([], USER_LANGUAGE, level_num, USER_TOPIC, USER_LENGTH)
            return result
    elif option == "too hard": 
        level_num-=1
        if level_num==0: 
            result, quiz =generate_article_and_quiz([], USER_LANGUAGE, level_num, USER_TOPIC, USER_LENGTH)
            return result
    else: 
        return None 
    new_level=get_key(level_num,dict)
    USER_LEVEL=new_level
    if current_user.is_authenticated:
        new_difficulty = LanguageDifficulty(level=new_level, language=USER_LANGUAGE, user_id=current_user.id)
        db.session.add(new_difficulty)
        db.session.commit()
    
    result, quiz=generate_article_and_quiz([], USER_LANGUAGE, new_level, USER_TOPIC, USER_LENGTH)
    return result

def paraphrase_text(article_text, complexity):
    # Define the complexity adjustment instructions
    language = detect_language(article_text)
    global USER_LANGUAGE
    USER_LANGUAGE = language
    
    if complexity == "too easy":
        instruction = f"Please paraphrase the following text to increase its complexity. Be sure to use {language}. The length of sentences should be increased by 10%, and the words should be replaced by less frequent words. Here's the article: \"{article_text}\""
    elif complexity == "too hard":
        instruction = f"Please paraphrase the following text to decrease its complexity. Be sure to use {language}. The length of sentences should be decreased by 10%, and the words should be replaced by more frequent words. Here's the article: \"{article_text}\"."
    else:
        return "Invalid complexity option. Please choose either 'too easy' or 'too hard'."

    # Prepare the system message
    messages = [
        { "role": "system", "content": instruction },
    ]

    # Call the Chat API
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo-0613",
        messages=messages,
        # You might want to adjust these parameters based on your needs
        temperature=0.7,
        max_tokens=500,
    )

    # Extract the paraphrased text from the model's response
    paraphrased_text = completion.choices[0].message.content

    return paraphrased_text

@app.route('/redo_article', methods=['POST'])
def redo_article():
    option = request.form['option']
    new_article_content = redo(option)
    return jsonify({"new_article_content": new_article_content})

@app.route('/result', methods=['POST'])
def result():
    generated_article_content = request.form['generated_article_content']
    return render_template('result.html', generated_article_content=generated_article_content)

@app.route('/generate_article', methods=['POST'])
def generate_article():
    language = request.form['languageSelect']
    difficulty = request.form['difficultySelect']
    topic = request.form['topicInput']
    length = request.form['lengthInput']

    generated_article_content, quiz_data = generate_article_and_quiz([], language, difficulty, topic, length)

    return jsonify({"generated_article_content": generated_article_content, "quiz_data": quiz_data})

@app.route('/translate', methods=['POST'])
def translate():
    data = request.get_json()
    text = data.get('text')
    translation = translator(text, USER_LANGUAGE)
    return jsonify({'translation': translation})

@app.route('/add_word', methods=['POST'])
@login_required
def add_word():
    data = request.get_json()
    word = data['word']
    translation = data['translation']

    new_word = WordList(word=word, translation=translation, user_id=current_user.id)
    db.session.add(new_word)
    db.session.commit()

    return jsonify({ 'status': 'success' })

def take_quiz():
    prompt = f"""Generate a multiple choice quiz with at most 6 questions in {USER_LANGUAGE} and give the answer key. 
    The quiz should be in the following format:

    {{
    "questions": [
        {{
        "question": "Sample Question?",
        "options": [
            "Option A",
            "Option B",
            "Option C",
            "Option D"
        ],
        "answer": "b) Option B"
        }}
        ...
    ]
    }}

    The multiple choice quiz should function like a reading comprehension quiz on the previous article and should quiz the user on their comprehension of the article. 
    Make sure that all questions can be answered solely based on the content from the previous article. Users should not be quizzed on things not mentioned in the previous article."""
    ""

    messages = [
        { "role": "system", "content": prompt },
    ]
    for question, answer in PREVIOUS[-MAX_CONTEXT_QUESTIONS:]:
        messages.append({ "role": "assistant", "content": answer })
 
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        top_p=1,
        frequency_penalty=FREQUENCY_PENALTY,
        presence_penalty=PRESENCE_PENALTY,
    )
    str=completion.choices[0].message.content
    messages = [
        { "role": "system", "content": f"convert this to json format {str}" },
    ]
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        top_p=1,
        frequency_penalty=FREQUENCY_PENALTY,
        presence_penalty=PRESENCE_PENALTY,
    )
    json_dict=completion.choices[0].message.content
    print(json_dict)
    data=json.loads(json_dict)
    result = {q["question"] + "\n" + "\n".join(q["options"]): q["answer"] for q in data["questions"]}
    return result

@app.route('/quiz')
def quiz():
    if 'quiz_data' not in session:
        session['quiz_data'] = take_quiz()
    
    quiz_data = session['quiz_data']
    quiz_json = json.dumps(quiz_data, ensure_ascii=False)
    quiz_json = json.dumps(quiz).replace("\n", "\\n")
    return render_template('quiz.html', quiz=quiz_data, quiz_json=quiz_json)

if __name__ == '__main__':
    app.run(debug=True)