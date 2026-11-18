"""Approved text queue. State is committed BEFORE Telegram: ambiguous sends never retry."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parent
CHANNEL = '@ai_assistent_gaid'
EXPECTED_BOT = 'neurohelp_posts_bot'
MSK = dt.timezone(dt.timedelta(hours=3))

def slot_at(now):
    # Catch up on delayed GitHub Actions runs within the same Moscow day.
    if 10 <= now.hour < 18:
        return 'morning'
    if 18 <= now.hour < 24:
        return 'evening'
    return None

def choose(posts, state, slot):
    ids = [p['id'] for p in posts]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate post ids')
    for post in posts:
        if post.get('approved') is True and post.get('slot') == slot and post['id'] not in state['posts']:
            if not isinstance(post.get('text'), str) or not 1 <= len(post['text']) <= 4000:
                raise ValueError('Approved post must contain 1-4000 characters')
            return post
    return None

def api(token, method, payload):
    request = urllib.request.Request(
        'https://api.telegram.org/bot' + token + '/' + method,
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except Exception:
        # Never print exceptions: urllib error strings may contain the secret URL.
        raise RuntimeError('Telegram request failed. Details withheld to protect the token.') from None
    if not result.get('ok'):
        raise RuntimeError('Telegram rejected the request; review bot permissions.')
    return result['result']

def check_connection(token):
    me = api(token, 'getMe', {})
    if me.get('username', '').lower() != EXPECTED_BOT:
        raise RuntimeError('Wrong bot token: expected @' + EXPECTED_BOT)
    chat = api(token, 'getChat', {'chat_id': CHANNEL})
    if chat.get('type') != 'channel':
        raise RuntimeError('The destination must be a channel')
    member = api(token, 'getChatMember', {'chat_id': CHANNEL, 'user_id': me['id']})
    if member.get('status') != 'administrator' or not member.get('can_post_messages'):
        raise RuntimeError('Bot needs channel administrator posting permission')
    print('Connection and posting permission verified. No message sent.')

def persist(state):
    (ROOT / 'state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    for command in [
        ['git', 'add', '_telegram/state.json'],
        ['git', 'commit', '-m', 'Record Telegram publication state [skip ci]'],
        ['git', 'push', 'origin', 'HEAD:main'],
    ]:
        if subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            raise RuntimeError('Could not save publication state. No automatic retry; inspect the workflow.')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['scheduled', 'check', 'preview'], default='preview')
    mode = parser.parse_args().mode
    posts = json.loads((ROOT / 'posts.json').read_text(encoding='utf8'))
    state = json.loads((ROOT / 'state.json').read_text(encoding='utf8'))
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    if mode == 'check':
        if not token:
            raise RuntimeError('Add the TELEGRAM_BOT_TOKEN repository secret first.')
        check_connection(token)
        return
    if mode == 'preview':
        for slot in ['morning', 'evening']:
            post = choose(posts, state, slot)
            print(slot + ': ' + (post['id'] if post else 'no approved posts'))
        print('Preview only. No Telegram request made.')
        return
    now = dt.datetime.now(MSK)
    slot = slot_at(now)
    if not slot:
        print('Outside the publication window. Skipped.')
        return
    key = now.date().isoformat() + '/' + slot
    if key in state['slots']:
        print('This slot is already sent or reserved. Skipped.')
        return
    post = choose(posts, state, slot)
    if not post:
        print('No approved post for this slot. Add approved content; nothing sent.')
        return
    if not token:
        raise RuntimeError('Add the TELEGRAM_BOT_TOKEN repository secret first.')
    check_connection(token)
    state['slots'][key] = {'post_id': post['id'], 'status': 'sending'}
    state['posts'][post['id']] = {'slot': key, 'status': 'sending'}
    persist(state)  # if this fails, do not contact sendMessage
    result = api(token, 'sendMessage', {'chat_id': CHANNEL, 'text': post['text']})
    state['slots'][key]['status'] = 'sent'
    state['posts'][post['id']].update(status='sent', message_id=result['message_id'])
    persist(state)
    print('Published approved post: ' + post['id'])

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error) if isinstance(error, (RuntimeError, ValueError)) else 'Publisher failed. Review configuration.')
        raise SystemExit(1)
