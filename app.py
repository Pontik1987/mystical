from flask import Flask, render_template, request, redirect, url_for, session, flash
from models import db, User, Post, Like, Comment, Follow, Bookmark, Notification, Message, Repost
from werkzeug.utils import secure_filename
from markupsafe import Markup, escape
import re
import os
from sqlalchemy import or_, and_

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'sqlite:///' + os.path.join(basedir, 'mysocial.db')
)
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

    def has_bookmarked(post):
        if not current_user:
            return False
        return Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None

    def unread_count():
        if not current_user:
            return 0
        return Notification.query.filter_by(user_id=current_user.id, is_read=False).count()

    def unread_messages_count():
        if not current_user:
            return 0
        return Message.query.filter_by(recipient_id=current_user.id, is_read=False).count()


    def has_reposted(post):
        if not current_user:
            return False
        return Repost.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None

    return dict(current_user=current_user, has_liked=has_liked, is_following=is_following,
                has_bookmarked=has_bookmarked, unread_count=unread_count,
                unread_messages_count=unread_messages_count, has_reposted=has_reposted)


@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    tab = request.args.get('tab', 'all')
    sort = request.args.get('sort', 'new')

    # Базовая выборка
    if tab == 'following':
        following_ids = [f.following_id for f in Follow.query.filter_by(follower_id=session['user_id']).all()]
        following_ids.append(session['user_id'])
        query = Post.query.filter(Post.user_id.in_(following_ids))
    else:
        query = Post.query

    # Сортировка
    if sort == 'popular':
        # По лайкам (много лайков — сверху)
        posts = query.all()
        posts.sort(key=lambda p: len(p.likes), reverse=True)
    elif sort == 'discussed':
        # По комментариям
        posts = query.all()
        posts.sort(key=lambda p: len(p.comments), reverse=True)
    else:
        # По дате (новые сверху)
        posts = query.order_by(Post.created_at.desc()).all()

    return render_template('index.html', posts=posts, tab=tab, sort=sort)


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

        if len(username) < 3:
            flash('Имя пользователя — минимум 3 символа')
            return redirect(url_for('register'))

        if len(username) > 20:
            flash('Имя пользователя — максимум 20 символов')
            return redirect(url_for('register'))

        if not re.match(r'^[a-z0-9_]+$', username):
            flash('Только латиница, цифры и _ (без пробелов и русских букв)')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash('Пароль — минимум 6 символов')
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
    if len(content) > 500:
        flash('Пост — максимум 500 символов')
        return redirect(url_for('index'))
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


@app.route('/user/<username>/followers')
def followers_list(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.filter_by(username=username.lower()).first()
    if not user:
        flash('Юзер не найден')
        return redirect(url_for('index'))

    follows = Follow.query.filter_by(following_id=user.id).all()
    users = [f.follower for f in follows]

    return render_template('followers.html', user=user, users=users, title='Подписчики')


@app.route('/user/<username>/following')
def following_list(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.filter_by(username=username.lower()).first()
    if not user:
        flash('Юзер не найден')
        return redirect(url_for('index'))

    follows = Follow.query.filter_by(follower_id=user.id).all()
    users = [f.following for f in follows]

    return render_template('following.html', user=user, users=users, title='Подписки')


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
        notif = Notification(
            user_id=user.id,
            actor_id=session['user_id'],
            type='follow'
        )
        db.session.add(notif)

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

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        current = request.form.get('current', '')
        new_pass = request.form.get('new_password', '')
        confirm = request.form.get('confirm', '')

        if not user.check_password(current):
            flash('Текущий пароль неверный')
            return redirect(url_for('change_password'))

        if len(new_pass) < 6:
            flash('Новый пароль должен быть минимум 6 символов')
            return redirect(url_for('change_password'))

        if new_pass != confirm:
            flash('Пароли не совпадают')
            return redirect(url_for('change_password'))

        if current == new_pass:
            flash('Новый пароль должен отличаться от текущего')
            return redirect(url_for('change_password'))

        user.set_password(new_pass)
        db.session.commit()

        flash('Пароль успешно изменён!')
        return redirect(url_for('profile', username=user.username))

    return render_template('change_password.html', user=user)



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
        # Уведомление автору поста (если это не свой пост)
        if post.user_id != session['user_id']:
            notif = Notification(
                user_id=post.user_id,
                actor_id=session['user_id'],
                type='like',
                post_id=post.id
            )
            db.session.add(notif)

    db.session.commit()

    next_url = request.form.get('next') or url_for('index')
    return redirect(next_url)


@app.route('/comment/<int:post_id>', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)
    content = request.form.get('content', '').strip()
    if len(content) > 300:
        flash('Комментарий — максимум 300 символов')
        next_url = request.form.get('next') or url_for('index')
        return redirect(next_url)

    if content:
        comment = Comment(content=content, user_id=session['user_id'], post_id=post.id)
        db.session.add(comment)
        # Уведомление автору поста
        if post.user_id != session['user_id']:
            notif = Notification(
                user_id=post.user_id,
                actor_id=session['user_id'],
                type='comment',
                post_id=post.id
            )
            db.session.add(notif)
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

@app.route('/bookmark/<int:post_id>', methods=['POST'])
def toggle_bookmark(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)
    existing = Bookmark.query.filter_by(user_id=session['user_id'], post_id=post.id).first()

    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Bookmark(user_id=session['user_id'], post_id=post.id))

    db.session.commit()

    next_url = request.form.get('next') or url_for('index')
    return redirect(next_url)


@app.route('/bookmarks')
def bookmarks():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    bookmarks_list = Bookmark.query.filter_by(user_id=session['user_id']).order_by(Bookmark.created_at.desc()).all()
    posts = [b.post for b in bookmarks_list]

    return render_template('bookmarks.html', posts=posts)

@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    items = Notification.query.filter_by(user_id=session['user_id']).order_by(Notification.created_at.desc()).all()

    # Отмечаем все как прочитанные
    for item in items:
        if not item.is_read:
            item.is_read = True
    db.session.commit()

    return render_template('notifications.html', notifications=items)

@app.route('/messages')
def messages():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    me = session['user_id']

    all_msgs = Message.query.filter(
        or_(Message.sender_id == me, Message.recipient_id == me)
    ).order_by(Message.created_at.desc()).all()

    seen = {}
    for msg in all_msgs:
        other_id = msg.recipient_id if msg.sender_id == me else msg.sender_id
        if other_id not in seen:
            seen[other_id] = msg

    dialogs = []
    for other_id, last_msg in seen.items():
        other = User.query.get(other_id)
        if not other:
            continue
        unread = Message.query.filter_by(
            sender_id=other_id, recipient_id=me, is_read=False
        ).count()
        dialogs.append({
            'user': other,
            'last_message': last_msg,
            'unread': unread
        })

    dialogs.sort(key=lambda d: d['last_message'].created_at, reverse=True)

    return render_template('messages.html', dialogs=dialogs)


@app.route('/chat/<username>')
def chat(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    other = User.query.filter_by(username=username.lower()).first()
    if not other:
        flash('Юзер не найден')
        return redirect(url_for('messages'))

    if other.id == session['user_id']:
        flash('Нельзя писать самому себе')
        return redirect(url_for('messages'))

    me = session['user_id']

    messages_list = Message.query.filter(
        or_(
            and_(Message.sender_id == me, Message.recipient_id == other.id),
            and_(Message.sender_id == other.id, Message.recipient_id == me)
        )
    ).order_by(Message.created_at.asc()).all()

    for msg in messages_list:
        if msg.recipient_id == me and not msg.is_read:
            msg.is_read = True
    db.session.commit()

    return render_template('chat.html', other=other, messages=messages_list)


@app.route('/send_message/<username>', methods=['POST'])
def send_message(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    other = User.query.filter_by(username=username.lower()).first()
    if not other:
        flash('Юзер не найден')
        return redirect(url_for('messages'))

    if other.id == session['user_id']:
        return redirect(url_for('messages'))

    content = request.form.get('content', '').strip()
    if len(content) > 1000:
        flash('Сообщение — максимум 1000 символов')
        return redirect(url_for('chat', username=other.username))
    if content:
        msg = Message(
            sender_id=session['user_id'],
            recipient_id=other.id,
            content=content
        )
        db.session.add(msg)
        db.session.commit()

    return redirect(url_for('chat', username=other.username))


@app.route('/api/chat/<username>')
def api_chat(username):
    if 'user_id' not in session:
        return {'error': 'unauthorized'}, 401

    other = User.query.filter_by(username=username.lower()).first()
    if not other:
        return {'error': 'not found'}, 404

    me = session['user_id']

    messages_list = Message.query.filter(
        or_(
            and_(Message.sender_id == me, Message.recipient_id == other.id),
            and_(Message.sender_id == other.id, Message.recipient_id == me)
        )
    ).order_by(Message.created_at.asc()).all()

    changed = False
    for msg in messages_list:
        if msg.recipient_id == me and not msg.is_read:
            msg.is_read = True
            changed = True
    if changed:
        db.session.commit()

    return {
        'messages': [
            {
                'id': m.id,
                'sender': m.sender.username,
                'content': m.content,
                'created_at': m.created_at.strftime('%d.%m %H:%M'),
                'is_mine': m.sender_id == me
            }
            for m in messages_list
        ]
    }

@app.route('/repost/<int:post_id>', methods=['POST'])
def toggle_repost(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)

    if post.user_id == session['user_id']:
        flash('Нельзя репостить свой пост')
        return redirect(request.form.get('next') or url_for('index'))

    existing = Repost.query.filter_by(user_id=session['user_id'], post_id=post.id).first()

    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Repost(user_id=session['user_id'], post_id=post.id))
        if post.user_id != session['user_id']:
            notif = Notification(
                user_id=post.user_id,
                actor_id=session['user_id'],
                type='repost',
                post_id=post.id
            )
            db.session.add(notif)

    db.session.commit()

    next_url = request.form.get('next') or url_for('index')
    return redirect(next_url)


@app.route('/post/<int:post_id>')
def single_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)

    # Увеличиваем счётчик просмотров
    post.views = (post.views or 0) + 1
    db.session.commit()

    return render_template('post.html', post=post)




@app.route('/edit_post/<int:post_id>', methods=['GET', 'POST'])
def edit_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)

    if post.user_id != session['user_id']:
        flash('Это не твой пост')
        return redirect(url_for('index'))

    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        if content:
            post.content = content
            db.session.commit()
            flash('Пост обновлён')
        next_url = request.form.get('next') or url_for('index')
        return redirect(next_url)

    return render_template('edit_post.html', post=post)



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
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
