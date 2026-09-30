from flask import Flask, render_template, request, redirect, url_for, session, flash
from models import db, User, Post, Like, Comment, Follow
from werkzeug.utils import secure_filename
from markupsafe import Markup, escape
from sqlalchemy import or_
import re
import os

app = Flask(__name__)
app.secret_key = 'change-me-to-random-secret-key'

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'mysocial.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

AVATAR_FOLDER = os.path.join(basedir, 'static', 'avatars')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
os.makedirs(AVATAR_FOLDER, exist_ok=True)

db.init_app(app)

TAG_REGEX = re.compile(r'#([a-zA-Zа-яА-Я0-9_]{1,50})')


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.template_filter('linkify')
def linkify_filter(text):
    """Превращает #tag в кликабельные ссылки, экранируя HTML."""
    if not text:
        return ''

    # Экранируем HTML
    safe_text = str(escape(text))

    def repl(match):
        tag = match.group(1).lower()
        url = url_for('tag_page', tag=tag)
        return f'<a href="{url}" class="hashtag">#{match.group(1)}</a>'

    return Markup(TAG_REGEX.sub(repl, safe_text))


@app.context_processor
def inject_user():
    current_user = None
    if 'user_id' in session:
        current_user = User.query.get(session['user_id'])

    def has_liked(post):
        if not current_user:
            return False
        return Like.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None

    def is_following(user):
        if not current_user or not user:
            return False
        if current_user.id == user.id:
            return False
        return Follow.query.filter_by(follower_id=current_user.id, following_id=user.id).first() is not None

    return dict(current_user=current_user, has_liked=has_liked, is_following=is_following)


@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    tab = request.args.get('tab', 'all')

    if tab == 'following':
        following_ids = [f.following_id for f in Follow.query.filter_by(follower_id=session['user_id']).all()]
        following_ids.append(session['user_id'])
        posts = Post.query.filter(Post.user_id.in_(following_ids)).order_by(Post.created_at.desc()).all()
    else:
        posts = Post.query.order_by(Post.created_at.desc()).all()

    return render_template('index.html', posts=posts, tab=tab)


@app.route('/search')
def search():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    q = request.args.get('q', '').strip()

    if not q:
        return render_template('search.html', query='', users=[], posts=[])

    users = User.query.filter(User.username.ilike(f'%{q}%')).order_by(User.username).all()
    posts = Post.query.filter(Post.content.ilike(f'%{q}%')).order_by(Post.created_at.desc()).all()

    return render_template('search.html', query=q, users=users, posts=posts)


@app.route('/tag/<tag>')
def tag_page(tag):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    tag = tag.lower()
    posts = Post.query.filter(Post.content.ilike(f'%#{tag}%')).order_by(Post.created_at.desc()).all()

    # Фильтруем точнее — по регулярке
    filtered = []
    for post in posts:
        found_tags = [m.group(1).lower() for m in TAG_REGEX.finditer(post.content or '')]
        if tag in found_tags:
            filtered.append(post)

    return render_template('tag.html', tag=tag, posts=filtered)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')

        if not username or not password:
            flash('Заполни все поля')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('Такой юзер уже есть')
            return redirect(url_for('register'))

        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('Регистрация успешна, заходи!')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('index'))

        flash('Неверный логин или пароль')
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/post', methods=['POST'])
def create_post():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    content = request.form.get('content', '').strip()
    if content:
        post = Post(content=content, user_id=session['user_id'])
        db.session.add(post)
        db.session.commit()

    return redirect(url_for('index'))


@app.route('/user/<username>')
def profile(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.filter_by(username=username.lower()).first()
    if not user:
        flash('Юзер не найден')
        return redirect(url_for('index'))

    posts = Post.query.filter_by(user_id=user.id).order_by(Post.created_at.desc()).all()

    followers_count = Follow.query.filter_by(following_id=user.id).count()
    following_count = Follow.query.filter_by(follower_id=user.id).count()

    return render_template(
        'profile.html',
        user=user,
        posts=posts,
        followers_count=followers_count,
        following_count=following_count
    )


@app.route('/follow/<username>', methods=['POST'])
def toggle_follow(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.filter_by(username=username.lower()).first()
    if not user:
        flash('Юзер не найден')
        return redirect(url_for('index'))

    if user.id == session['user_id']:
        flash('На себя подписаться нельзя')
        return redirect(url_for('profile', username=user.username))

    existing = Follow.query.filter_by(follower_id=session['user_id'], following_id=user.id).first()

    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Follow(follower_id=session['user_id'], following_id=user.id))

    db.session.commit()

    next_url = request.form.get('next') or url_for('profile', username=user.username)
    return redirect(next_url)


@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        bio = request.form.get('bio', '').strip()
        city = request.form.get('city', '').strip()
        website = request.form.get('website', '').strip()

        if len(bio) > 300:
            flash('Bio слишком длинное (макс 300 символов)')
            return redirect(url_for('edit_profile'))

        user.bio = bio or None
        user.city = city or None
        user.website = website or None
        db.session.commit()

        flash('Профиль обновлён!')
        return redirect(url_for('profile', username=user.username))

    return render_template('edit_profile.html', user=user)


@app.route('/like/<int:post_id>', methods=['POST'])
def toggle_like(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)
    existing = Like.query.filter_by(user_id=session['user_id'], post_id=post.id).first()

    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Like(user_id=session['user_id'], post_id=post.id))

    db.session.commit()

    next_url = request.form.get('next') or url_for('index')
    return redirect(next_url)


@app.route('/comment/<int:post_id>', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)
    content = request.form.get('content', '').strip()

    if content:
        comment = Comment(content=content, user_id=session['user_id'], post_id=post.id)
        db.session.add(comment)
        db.session.commit()

    next_url = request.form.get('next') or url_for('index')
    return redirect(next_url)


@app.route('/delete_post/<int:post_id>', methods=['POST'])
def delete_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)

    if post.user_id != session['user_id']:
        flash('Это не твой пост')
        return redirect(url_for('index'))

    db.session.delete(post)
    db.session.commit()

    flash('Пост удалён')
    next_url = request.form.get('next') or url_for('index')
    return redirect(next_url)


@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
def delete_comment(comment_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    comment = Comment.query.get_or_404(comment_id)

    if comment.user_id != session['user_id']:
        flash('Это не твой комментарий')
        return redirect(url_for('index'))

    db.session.delete(comment)
    db.session.commit()

    next_url = request.form.get('next') or url_for('index')
    return redirect(next_url)


@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    file = request.files.get('avatar')
    if not file or file.filename == '':
        flash('Выбери файл')
        return redirect(url_for('profile', username=session['username']))

    if not allowed_file(file.filename):
        flash('Только png, jpg, jpeg, gif, webp')
        return redirect(url_for('profile', username=session['username']))

    user = User.query.get(session['user_id'])

    if user.avatar:
        old_path = os.path.join(AVATAR_FOLDER, user.avatar)
        if os.path.exists(old_path):
            os.remove(old_path)

    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"user_{user.id}.{ext}"
    file.save(os.path.join(AVATAR_FOLDER, filename))

    user.avatar = filename
    db.session.commit()

    flash('Аватарка обновлена!')
    return redirect(url_for('profile', username=user.username))


with app.app_context():
    db.create_all()


if __name__ == '__main__':
    app.run(debug=True)
