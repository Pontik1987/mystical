from flask import Flask, render_template, request, redirect, url_for, session, flash
from models import db, User, Post, Like, Comment, Follow, Bookmark, Notification, Message, Repost, Poll, PollOption, PollVote, Block, Report, PinnedChat, GroupChat, GroupMember, GroupMessage, Story, StoryView
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
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
STORIES_FOLDER = os.path.join(basedir, 'static', 'stories')
os.makedirs(STORIES_FOLDER, exist_ok=True)
VIDEOS_FOLDER = os.path.join(basedir, 'static', 'videos')
os.makedirs(VIDEOS_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov'}
os.makedirs(AVATAR_FOLDER, exist_ok=True)

db.init_app(app)

TAG_REGEX = re.compile(r'#([a-zA-Zа-яА-Я0-9_]{1,50})')


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_video(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS


@app.template_filter('linkify')
def linkify_filter(text):
    """Превращает #tag и @username в кликабельные ссылки, экранируя HTML."""
    if not text:
        return ''

    # Экранируем HTML
    safe_text = str(escape(text))

    # Сначала хэштеги
    def repl_tag(match):
        tag = match.group(1).lower()
        url = url_for('tag_page', tag=tag)
        return f'<a href="{url}" class="hashtag">#{match.group(1)}</a>'

    safe_text = TAG_REGEX.sub(repl_tag, safe_text)

    # Потом упоминания
    def repl_mention(match):
        username = match.group(1).lower()
        url = url_for('profile', username=username)
        return f'<a href="{url}" class="mention">@{match.group(1)}</a>'

    mention_regex = re.compile(r'@([a-zA-Z0-9_]{1,30})')
    safe_text = mention_regex.sub(repl_mention, safe_text)

    return Markup(safe_text)


@app.context_processor
def inject_user():
    current_user = None
    if 'user_id' in session:
        current_user = User.query.get(session['user_id'])

    def has_liked(post):
        if not current_user:
            return False
        return Like.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None

    def my_reaction(post):
        if not current_user:
            return None
        like = Like.query.filter_by(user_id=current_user.id, post_id=post.id).first()
        return like.reaction if like else None

    def count_reaction(post, reaction):
        return Like.query.filter_by(post_id=post.id, reaction=reaction).count()

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

    def is_blocked(user):
        if not current_user or not user:
            return False
        if current_user.id == user.id:
            return False
        # Проверяем обе стороны: я заблокировал или меня
        return Block.query.filter(
            db.or_(
                db.and_(Block.user_id == current_user.id, Block.blocked_id == user.id),
                db.and_(Block.user_id == user.id, Block.blocked_id == current_user.id)
            )
        ).first() is not None

    def blocked_ids():
        if not current_user:
            return []
        my_blocks = [b.blocked_id for b in Block.query.filter_by(user_id=current_user.id).all()]
        blocked_me = [b.user_id for b in Block.query.filter_by(blocked_id=current_user.id).all()]
        return list(set(my_blocks + blocked_me))

    def is_admin():
        if not current_user:
            return False
        return current_user.id == 1  # первый юзер — админ

    def has_reported_post(post):
        if not current_user:
            return False
        return Report.query.filter_by(reporter_id=current_user.id, post_id=post.id).first() is not None

    def is_chat_pinned(other_user):
        if not current_user or not other_user:
            return False
        return PinnedChat.query.filter_by(user_id=current_user.id, other_id=other_user.id).first() is not None

    def accent_class(user):
        if not user or not user.accent_color:
            return 'accent-purple'
        return f'accent-{user.accent_color}'

    return dict(current_user=current_user, has_liked=has_liked, is_following=is_following,
                has_bookmarked=has_bookmarked, unread_count=unread_count,
                unread_messages_count=unread_messages_count, has_reposted=has_reposted,
                my_reaction=my_reaction, count_reaction=count_reaction,
                is_blocked=is_blocked, blocked_ids=blocked_ids,
                is_admin=is_admin, has_reported_post=has_reported_post,
                is_chat_pinned=is_chat_pinned, accent_class=accent_class)


@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    tab = request.args.get('tab', 'all')
    sort = request.args.get('sort', 'new')

    # Заблокированные (я заблокировал + меня)
    me = session['user_id']
    my_blocks = [b.blocked_id for b in Block.query.filter_by(user_id=me).all()]
    blocked_me = [b.user_id for b in Block.query.filter_by(blocked_id=me).all()]
    blocked = list(set(my_blocks + blocked_me))

    # Базовая выборка
    if tab == 'following':
        following_ids = [f.following_id for f in Follow.query.filter_by(follower_id=session['user_id']).all()]
        following_ids.append(session['user_id'])
        query = Post.query.filter(Post.user_id.in_(following_ids))
    else:
        query = Post.query

    # Исключаем заблокированных
    if blocked:
        query = query.filter(Post.user_id.notin_(blocked))

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

    # Последние истории (не истёкшие, кроме своих)
    now = datetime.utcnow()
    recent_stories = Story.query.filter(
        Story.expires_at > now,
        Story.user_id != session['user_id']
    ).order_by(Story.created_at.desc()).limit(20).all()

    return render_template('index.html', posts=posts, tab=tab, sort=sort, recent_stories=recent_stories)


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

        # Обработка видео
        video_file = request.files.get('video')
        if video_file and video_file.filename:
            if allowed_video(video_file.filename):
                # Проверяем размер (50 МБ)
                video_file.seek(0, 2)  # в конец
                size = video_file.tell()
                video_file.seek(0)

                if size > 50 * 1024 * 1024:
                    flash('Видео — максимум 50 МБ')
                    return redirect(url_for('index'))

                ext = video_file.filename.rsplit('.', 1)[1].lower()
                v_filename = f"video_{session['user_id']}_{int(datetime.utcnow().timestamp())}.{ext}"
                video_file.save(os.path.join(VIDEOS_FOLDER, v_filename))
                post.video = v_filename
            else:
                flash('Видео: только mp4, webm, mov')
                return redirect(url_for('index'))

        db.session.add(post)
        db.session.flush()  # получаем post.id

        # Обработка опроса
        poll_question = request.form.get('poll_question', '').strip()
        if poll_question:
            options = []
            for i in range(2, 5):
                opt = request.form.get(f'poll_option_{i}', '').strip()
                if opt:
                    options.append(opt)

            if len(options) >= 2:
                poll = Poll(question=poll_question[:300], post_id=post.id)
                db.session.add(poll)
                db.session.flush()

                for opt_text in options:
                    db.session.add(PollOption(text=opt_text[:200], poll_id=poll.id))

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

    # Закреплённый пост — всегда сверху, потом остальные по дате
    posts = Post.query.filter_by(user_id=user.id).order_by(
        Post.is_pinned.desc(),
        Post.created_at.desc()
    ).all()

    followers_count = Follow.query.filter_by(following_id=user.id).count()
    following_count = Follow.query.filter_by(follower_id=user.id).count()

    return render_template(
        'profile.html',
        user=user,
        posts=posts,
        followers_count=followers_count,
        following_count=following_count
    )


@app.route('/user/<username>/stats')
def user_stats(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.filter_by(username=username.lower()).first()
    if not user:
        flash('Юзер не найден')
        return redirect(url_for('index'))

    # Все посты юзера
    posts = Post.query.filter_by(user_id=user.id).all()

    # Общая статистика
    total_posts = len(posts)
    total_likes = sum(len(p.likes) for p in posts)
    total_comments = sum(len(p.comments) for p in posts)
    total_reposts = sum(len(p.post_reposts) for p in posts)
    total_views = sum(p.views or 0 for p in posts)

    # Топ-3 по лайкам
    top_liked = sorted(posts, key=lambda p: len(p.likes), reverse=True)[:3]

    # Топ-3 по комментариям
    top_commented = sorted(posts, key=lambda p: len(p.comments), reverse=True)[:3]

    # Топ-3 по просмотрам
    top_viewed = sorted(posts, key=lambda p: (p.views or 0), reverse=True)[:3]

    # Социалка
    followers_count = Follow.query.filter_by(following_id=user.id).count()
    following_count = Follow.query.filter_by(follower_id=user.id).count()

    # Сообщения
    total_messages = Message.query.filter_by(sender_id=user.id).count()

    # Реакции по типам
    reactions = {
        'like': 0,
        'class': 0,
        'funny': 0,
        'wow': 0
    }
    for post in posts:
        for like in post.likes:
            if like.reaction in reactions:
                reactions[like.reaction] += 1

    return render_template(
        'stats.html',
        user=user,
        total_posts=total_posts,
        total_likes=total_likes,
        total_comments=total_comments,
        total_reposts=total_reposts,
        total_views=total_views,
        top_liked=top_liked,
        top_commented=top_commented,
        top_viewed=top_viewed,
        followers_count=followers_count,
        following_count=following_count,
        total_messages=total_messages,
        reactions=reactions
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
        accent = request.form.get('accent_color', 'purple').strip()

        if len(bio) > 300:
            flash('Bio слишком длинное (макс 300 символов)')
            return redirect(url_for('edit_profile'))

        # Белый список цветов
        allowed_colors = ['purple', 'blue', 'green', 'orange', 'red', 'dark']
        if accent not in allowed_colors:
            accent = 'purple'

        user.bio = bio or None
        user.city = city or None
        user.website = website or None
        user.accent_color = accent
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
    reaction = request.form.get('reaction', 'like')

    existing = Like.query.filter_by(user_id=session['user_id'], post_id=post.id).first()

    if existing:
        if existing.reaction == reaction:
            # Та же реакция — убираем
            db.session.delete(existing)
        else:
            # Другая реакция — меняем
            existing.reaction = reaction
    else:
        # Новая реакция
        db.session.add(Like(user_id=session['user_id'], post_id=post.id, reaction=reaction))
        # Уведомление автору
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


@app.route('/notification/<int:notif_id>/delete', methods=['POST'])
def delete_notification(notif_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    notif = Notification.query.get_or_404(notif_id)

    if notif.user_id != session['user_id']:
        flash('Это не твоё уведомление')
        return redirect(url_for('notifications'))

    db.session.delete(notif)
    db.session.commit()

    return redirect(url_for('notifications'))


@app.route('/notifications/clear', methods=['POST'])
def clear_notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    Notification.query.filter_by(user_id=session['user_id']).delete()
    db.session.commit()

    flash('Уведомления очищены')
    return redirect(url_for('notifications'))

@app.route('/pin_chat/<username>', methods=['POST'])
def toggle_pin_chat(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    other = User.query.filter_by(username=username.lower()).first()
    if not other or other.id == session['user_id']:
        flash('Юзер не найден')
        return redirect(url_for('messages'))

    existing = PinnedChat.query.filter_by(user_id=session['user_id'], other_id=other.id).first()

    if existing:
        db.session.delete(existing)
    else:
        db.session.add(PinnedChat(user_id=session['user_id'], other_id=other.id))

    db.session.commit()

    return redirect(url_for('messages'))


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

    # Закреплённые
    pinned_ids = [p.other_id for p in PinnedChat.query.filter_by(user_id=me).all()]

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
            'unread': unread,
            'is_pinned': other.id in pinned_ids
        })

    # Сортировка: сначала закреплённые, потом по дате
    dialogs.sort(key=lambda d: (not d['is_pinned'], -d['last_message'].created_at.timestamp()))

    pinned = [d for d in dialogs if d['is_pinned']]
    others = [d for d in dialogs if not d['is_pinned']]

    return render_template('messages.html', dialogs=dialogs, pinned=pinned, others=others)


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

@app.route('/vote/<int:option_id>', methods=['POST'])
def vote(option_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    option = PollOption.query.get_or_404(option_id)
    poll = option.poll

    # Проверяем, голосовал ли уже
    existing = PollVote.query.join(PollOption).filter(
        PollOption.poll_id == poll.id,
        PollVote.user_id == session['user_id']
    ).first()

    if existing:
        if existing.option_id == option.id:
            # Тот же вариант — отменяем голос
            db.session.delete(existing)
        else:
            # Меняем голос
            existing.option_id = option.id
    else:
        db.session.add(PollVote(user_id=session['user_id'], option_id=option.id))

    db.session.commit()

    next_url = request.form.get('next') or url_for('index')
    return redirect(next_url)


@app.route('/pin/<int:post_id>', methods=['POST'])
def toggle_pin(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)

    if post.user_id != session['user_id']:
        flash('Можно закрепить только свой пост')
        return redirect(url_for('index'))

    if post.is_pinned:
        # Открепляем
        post.is_pinned = False
    else:
        # Открепляем все свои посты
        Post.query.filter_by(user_id=session['user_id'], is_pinned=True).update({'is_pinned': False})
        # Закрепляем этот
        post.is_pinned = True

    db.session.commit()

    next_url = request.form.get('next') or url_for('profile', username=session['username'])
    return redirect(next_url)


@app.route('/report/post/<int:post_id>', methods=['GET', 'POST'])
def report_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)

    if post.user_id == session['user_id']:
        flash('Нельзя пожаловаться на свой пост')
        return redirect(url_for('index'))

    existing = Report.query.filter_by(reporter_id=session['user_id'], post_id=post.id).first()
    if existing:
        flash('Ты уже пожаловался на этот пост')
        return redirect(url_for('index'))

    if request.method == 'POST':
        reason = request.form.get('reason', 'other')
        details = request.form.get('details', '').strip()

        report = Report(
            reporter_id=session['user_id'],
            post_id=post.id,
            reason=reason,
            details=details or None
        )
        db.session.add(report)
        db.session.commit()

        flash('Жалоба отправлена')
        return redirect(url_for('index'))

    return render_template('report.html', post=post, comment=None)


@app.route('/report/comment/<int:comment_id>', methods=['GET', 'POST'])
def report_comment(comment_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    comment = Comment.query.get_or_404(comment_id)

    if comment.user_id == session['user_id']:
        flash('Нельзя пожаловаться на свой комментарий')
        return redirect(url_for('index'))

    existing = Report.query.filter_by(reporter_id=session['user_id'], comment_id=comment.id).first()
    if existing:
        flash('Ты уже пожаловался на этот комментарий')
        return redirect(url_for('index'))

    if request.method == 'POST':
        reason = request.form.get('reason', 'other')
        details = request.form.get('details', '').strip()

        report = Report(
            reporter_id=session['user_id'],
            comment_id=comment.id,
            reason=reason,
            details=details or None
        )
        db.session.add(report)
        db.session.commit()

        flash('Жалоба отправлена')
        return redirect(url_for('index'))

    return render_template('report.html', post=None, comment=comment)


@app.route('/admin/reports')
def admin_reports():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session['user_id'] != 1:
        flash('Доступ только для админа')
        return redirect(url_for('index'))

    reports = Report.query.filter_by(is_resolved=False).order_by(Report.created_at.desc()).all()
    return render_template('admin_reports.html', reports=reports)


@app.route('/admin/report/<int:report_id>/dismiss', methods=['POST'])
def dismiss_report(report_id):
    if 'user_id' not in session or session['user_id'] != 1:
        return redirect(url_for('index'))

    report = Report.query.get_or_404(report_id)
    report.is_resolved = True
    db.session.commit()

    flash('Жалоба отклонена')
    return redirect(url_for('admin_reports'))


@app.route('/admin/report/<int:report_id>/delete_post', methods=['POST'])
def admin_delete_post(report_id):
    if 'user_id' not in session or session['user_id'] != 1:
        return redirect(url_for('index'))

    report = Report.query.get_or_404(report_id)

    if report.post:
        db.session.delete(report.post)
        report.is_resolved = True
        db.session.commit()
        flash('Пост удалён, жалоба закрыта')
    elif report.comment:
        db.session.delete(report.comment)
        report.is_resolved = True
        db.session.commit()
        flash('Комментарий удалён, жалоба закрыта')

    return redirect(url_for('admin_reports'))


@app.route('/block/<username>', methods=['POST'])
def block_user(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.filter_by(username=username.lower()).first()
    if not user:
        flash('Юзер не найден')
        return redirect(url_for('index'))

    if user.id == session['user_id']:
        flash('Нельзя заблокировать себя')
        return redirect(url_for('profile', username=user.username))

    # Если уже заблокирован — разблокируем
    existing = Block.query.filter_by(user_id=session['user_id'], blocked_id=user.id).first()
    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Block(user_id=session['user_id'], blocked_id=user.id))
        # Автоотписка в обе стороны
        Follow.query.filter_by(follower_id=session['user_id'], following_id=user.id).delete()
        Follow.query.filter_by(follower_id=user.id, following_id=session['user_id']).delete()

    db.session.commit()

    next_url = request.form.get('next') or url_for('profile', username=user.username)
    return redirect(next_url)


@app.route('/blocked')
def blocked_list():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    blocks = Block.query.filter_by(user_id=session['user_id']).all()
    users = [b.blocked for b in blocks]

    return render_template('blocked.html', users=users)


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


@app.route('/manifest.json')
def manifest():
    """Отдаём PWA-манифест с правильной кодировкой."""
    from flask import send_from_directory
    response = send_from_directory('static', 'manifest.json', mimetype='application/json')
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response


@app.route('/sw.js')
def service_worker():
    """Отдаём service worker из корня (для правильного scope)."""
    from flask import send_from_directory
    response = send_from_directory('static', 'sw.js', mimetype='application/javascript')
    response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    response.headers['Service-Worker-Allowed'] = '/'
    return response


@app.route('/groups')
def groups():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Группы, где я участник
    memberships = GroupMember.query.filter_by(user_id=session['user_id']).all()
    groups_list = [m.group for m in memberships]

    return render_template('groups.html', groups=groups_list)


@app.route('/group/create', methods=['GET', 'POST'])
def create_group():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Все юзеры кроме меня
    all_users = User.query.filter(User.id != session['user_id']).order_by(User.username).all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        member_ids = request.form.getlist('members')

        if not name:
            flash('Введи название группы')
            return redirect(url_for('create_group'))

        if len(name) > 100:
            flash('Название — максимум 100 символов')
            return redirect(url_for('create_group'))

        if len(member_ids) < 2:
            flash('Выбери минимум 2 участников')
            return redirect(url_for('create_group'))

        group = GroupChat(name=name, creator_id=session['user_id'])
        db.session.add(group)
        db.session.flush()

        # Добавляем создателя
        db.session.add(GroupMember(user_id=session['user_id'], group_id=group.id))

        # Добавляем остальных
        for uid in member_ids:
            try:
                db.session.add(GroupMember(user_id=int(uid), group_id=group.id))
            except:
                pass

        db.session.commit()

        flash(f'Группа «{name}» создана!')
        return redirect(url_for('group_chat', group_id=group.id))

    return render_template('create_group.html', all_users=all_users)


@app.route('/group/<int:group_id>')
def group_chat(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    group = GroupChat.query.get_or_404(group_id)

    # Проверяем, что я участник
    is_member = GroupMember.query.filter_by(user_id=session['user_id'], group_id=group.id).first()
    if not is_member:
        flash('Ты не участник этой группы')
        return redirect(url_for('groups'))

    messages = GroupMessage.query.filter_by(group_id=group.id).order_by(GroupMessage.created_at).all()
    members = [m.user for m in group.members]

    return render_template('group_chat.html', group=group, messages=messages, members=members)


@app.route('/group/<int:group_id>/send', methods=['POST'])
def group_send(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    group = GroupChat.query.get_or_404(group_id)
    is_member = GroupMember.query.filter_by(user_id=session['user_id'], group_id=group.id).first()
    if not is_member:
        return redirect(url_for('groups'))

    content = request.form.get('content', '').strip()
    if content:
        if len(content) > 1000:
            flash('Сообщение — максимум 1000 символов')
            return redirect(url_for('group_chat', group_id=group.id))

        msg = GroupMessage(content=content, sender_id=session['user_id'], group_id=group.id)
        db.session.add(msg)
        db.session.commit()

    return redirect(url_for('group_chat', group_id=group.id))


@app.route('/group/<int:group_id>/leave', methods=['POST'])
def group_leave(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    group = GroupChat.query.get_or_404(group_id)
    membership = GroupMember.query.filter_by(user_id=session['user_id'], group_id=group.id).first()

    if membership:
        db.session.delete(membership)
        db.session.commit()
        flash('Ты вышел из группы')

    # Если группа пустая — удаляем её
    if not group.members:
        db.session.delete(group)
        db.session.commit()

    return redirect(url_for('groups'))


@app.route('/group/<int:group_id>/add', methods=['POST'])
def group_add_member(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    group = GroupChat.query.get_or_404(group_id)

    # Только создатель может добавлять
    if group.creator_id != session['user_id']:
        flash('Только создатель может добавлять')
        return redirect(url_for('group_chat', group_id=group.id))

    user_id = request.form.get('user_id', type=int)
    if user_id:
        existing = GroupMember.query.filter_by(user_id=user_id, group_id=group.id).first()
        if not existing:
            db.session.add(GroupMember(user_id=user_id, group_id=group.id))
            db.session.commit()

    return redirect(url_for('group_chat', group_id=group.id))


@app.route('/group/<int:group_id>/remove/<int:user_id>', methods=['POST'])
def group_remove_member(group_id, user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    group = GroupChat.query.get_or_404(group_id)

    if group.creator_id != session['user_id']:
        flash('Только создатель может удалять')
        return redirect(url_for('group_chat', group_id=group.id))

    if user_id == group.creator_id:
        flash('Нельзя удалить создателя')
        return redirect(url_for('group_chat', group_id=group.id))

    membership = GroupMember.query.filter_by(user_id=user_id, group_id=group.id).first()
    if membership:
        db.session.delete(membership)
        db.session.commit()

    return redirect(url_for('group_chat', group_id=group.id))


@app.route('/stories')
def stories_list():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Только не истёкшие истории
    now = datetime.utcnow()
    stories = Story.query.filter(Story.expires_at > now).order_by(Story.created_at.desc()).all()

    # Группируем по авторам
    by_author = {}
    for s in stories:
        if s.user_id not in by_author:
            by_author[s.user_id] = []
        by_author[s.user_id].append(s)

    # Свои истории отдельно
    my_stories = by_author.pop(session['user_id'], [])

    return render_template('stories.html', my_stories=my_stories, by_author=by_author)


@app.route('/story/create', methods=['GET', 'POST'])
def create_story():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        file = request.files.get('image')
        caption = request.form.get('caption', '').strip()

        if not file or file.filename == '':
            flash('Выбери фото')
            return redirect(url_for('create_story'))

        if not allowed_file(file.filename):
            flash('Только png, jpg, jpeg, gif, webp')
            return redirect(url_for('create_story'))

        if len(caption) > 300:
            flash('Подпись — максимум 300 символов')
            return redirect(url_for('create_story'))

        # Сохраняем файл
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"story_{session['user_id']}_{int(datetime.utcnow().timestamp())}.{ext}"
        file.save(os.path.join(STORIES_FOLDER, filename))

        # Создаём историю на 24 часа
        story = Story(
            image=filename,
            caption=caption or None,
            user_id=session['user_id'],
            expires_at=datetime.utcnow() + timedelta(hours=24)
        )
        db.session.add(story)
        db.session.commit()

        flash('История создана! Живёт 24 часа.')
        return redirect(url_for('index'))

    return render_template('create_story.html')


@app.route('/story/<int:story_id>')
def story_view(story_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    story = Story.query.get_or_404(story_id)

    if story.is_expired():
        flash('История уже истекла')
        return redirect(url_for('index'))

    # Отмечаем просмотр (если это не моя история)
    if story.user_id != session['user_id']:
        existing = StoryView.query.filter_by(user_id=session['user_id'], story_id=story.id).first()
        if not existing:
            db.session.add(StoryView(user_id=session['user_id'], story_id=story.id))
            db.session.commit()

    # Все истории этого автора для пролистывания
    now = datetime.utcnow()
    author_stories = Story.query.filter(
        Story.user_id == story.user_id,
        Story.expires_at > now
    ).order_by(Story.created_at.asc()).all()

    return render_template('story_view.html', story=story, author_stories=author_stories)


@app.route('/story/<int:story_id>/delete', methods=['POST'])
def delete_story(story_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    story = Story.query.get_or_404(story_id)

    if story.user_id != session['user_id']:
        flash('Это не твоя история')
        return redirect(url_for('index'))

    # Удаляем файл
    filepath = os.path.join(STORIES_FOLDER, story.image)
    if os.path.exists(filepath):
        os.remove(filepath)

    db.session.delete(story)
    db.session.commit()

    flash('История удалена')
    return redirect(url_for('index'))


with app.app_context():
    db.create_all()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
