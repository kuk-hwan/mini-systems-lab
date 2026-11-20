"""Render and handle the quiz with Python, using ordinary HTML forms."""

from html import escape
from math import ceil
from pathlib import Path
from string import Template

from quiz import HINT_SECONDS, QUESTIONS, ROUND_SECONDS


WEB = Path(__file__).with_name('quiz_web')
TEMPLATE = Template((WEB / 'index.html').read_text(encoding='utf-8'))
TOTAL = len(QUESTIONS)
HINT_RETRY = '힌트 시간이 끝났어요. 다시 조회해서 MISS를 확인해 보세요.'
HINT_MISS = '캐시가 만료돼 힌트를 가져올 수 없어요.'


def countdown(left, final_label):
    label = f'{ceil(left)}초' if left > 0 else final_label
    if left <= 0:
        return escape(label)
    slots = []
    for seconds in range(ceil(left), 0, -1):
        begin = max(0, left - seconds)
        duration = left - (seconds - 1) - begin
        slots.append(
            f'<span class="time-slot" style="--delay:{begin:.3f}s;'
            f'--duration:{duration:.3f}s">{seconds}초</span>'
        )
    slots.append(
        f'<span class="time-final" style="--delay:{left:.3f}s">{escape(final_label)}</span>'
    )
    return (
        f'<span class="countdown" role="timer" aria-label="{label}">'
        f'<span class="time-digits" aria-hidden="true">{"".join(slots)}</span></span>'
    )


def meter(left, duration, label, running=True):
    animation = ' running' if running and left > 0 else ''
    return (
        f'<div class="meter{animation}" role="progressbar" aria-label="{label}" '
        f'aria-valuemin="0" aria-valuemax="{duration}" aria-valuenow="{ceil(left)}" '
        f'style="--remaining:{left / duration:.5f};--duration:{left:.3f}s">'
        '<span></span></div>'
    )


def action_button(path, label, kind='primary', arrow='→'):
    return (
        f'<form method="post" action="{path}"><button class="{kind}" type="submit">'
        f'{escape(label)} <span aria-hidden="true">{arrow}</span></button></form>'
    )


class QuizPages:
    def __init__(self, quiz):
        self.quiz = quiz

    def start(self):
        token = self.quiz.start(0)['token']
        return f'/quiz/{token}'

    def act(self, token, action, choice=None):
        path = f'/quiz/{token}'
        with self.quiz.cache.lock:
            state = self.quiz.get_round(token)
            if action == 'answer':
                self.quiz.answer(token, choice)
            elif action == 'hint':
                event = self.quiz.hint(token)
                events = [event, *state.get('hint_events', [])][:5]
                self.quiz.save_round(token, {**state, 'hint_events': events})
            elif action == 'next':
                if 'result' not in state:
                    raise ValueError('Submit an answer before going to the next question')
                if state['index'] + 1 == TOTAL:
                    return path + '/result'
                next_token = state.get('next_token')
                if next_token is None:
                    history = self.history(state)
                    next_token = self.quiz.start(state['index'] + 1, history)['token']
                    self.quiz.save_round(token, {**state, 'next_token': next_token})
                return f'/quiz/{next_token}'
            else:
                raise LookupError('Unknown quiz action')
        return path

    def history(self, state):
        history = state['history']
        if 'result' in state:
            return [*history, {'index': state['index'], **state['result']}]
        return history

    def play(self, token, show_results=False):
        with self.quiz.cache.lock:
            state = self.quiz.get_round(token)
            now = self.quiz.clock()
            if 'result' not in state and now >= state['deadline']:
                self.quiz.answer(token, None)
                state = self.quiz.get_round(token)
        results = self.history(state)
        if show_results and len(results) != TOTAL:
            raise LookupError('Finish the quiz first')
        path = f'/quiz/{token}'
        left = max(0, state['deadline'] - state.get('answered_at', now))
        running = 'result' not in state
        refresh = f'<meta http-equiv="refresh" content="{ceil(left)}">' if running else ''
        return self.render(
            stage=self.results(results) if show_results else self.round(path, state, left),
            hint=self.hint_panel(path, state, now),
            events=self.event_panel(token, state.get('hint_events', [])),
            completed=len(results), index=state['index'], active=not show_results,
            refresh=refresh,
        )

    def intro(self, message=''):
        stage = f'''
          <div class="stage intro">
            <div class="timer-art" aria-hidden="true">
              <div class="art-orbit orbit-outer"></div><div class="art-orbit orbit-inner"></div>
              <div class="art-dot"></div><div class="art-tag">TTL</div>
              <div class="clock-face"><span></span></div>
              <div class="art-tag art-tag-time">00:{HINT_SECONDS:02}</div>
            </div>
            <div class="intro-copy">
              <h2>힌트를 꺼낼 시간은<br>딱 {HINT_SECONDS}초.</h2>
              <p>문제는 총 {TOTAL}개예요. 각 문제에 {ROUND_SECONDS}초가 주어지고,
                힌트는 문제가 시작된 뒤 {HINT_SECONDS}초 동안 조회할 수 있어요.</p>
              {action_button('/quiz/start', '퀴즈 시작')}
            </div>
          </div>'''
        hint = f'''
          <div class="hint-heading"><h2>Redis 힌트</h2><span class="hint-time">{HINT_SECONDS}초</span></div>
          {meter(HINT_SECONDS, HINT_SECONDS, '힌트의 남은 시간', False)}
          <p>문제를 시작하면 힌트가 캐시에 저장돼요.</p>
          <button class="hint-button" type="button" disabled>힌트 조회 <span aria-hidden="true">↗</span></button>'''
        return self.render(stage, hint, '<p>퀴즈를 시작하면 캐시 동작이 여기에 표시돼요.</p>', message=message)

    def round(self, path, state, left):
        index = state['index']
        question = QUESTIONS[index]
        result = state.get('result')
        timer = countdown(left, '0초') if result is None else f'{ceil(left)}초'
        choices = []
        for choice, option in enumerate(question['options']):
            classes = 'option'
            if result and choice == result['answer']:
                classes += ' right'
            elif result and choice == result['selected']:
                classes += ' wrong'
            disabled = ' disabled' if result else ''
            choices.append(
                f'<button class="{classes}" type="submit" name="choice" value="{choice}"{disabled}>'
                f'<span aria-hidden="true">{chr(65 + choice)}</span>{escape(option)}</button>'
            )
        feedback = ''
        if result:
            title = '시간이 끝났어요.' if result['timed_out'] else '정답이에요.' if result['correct'] else '아쉬워요.'
            answer = escape(question['options'][result['answer']])
            next_label = '결과 보기' if index + 1 == TOTAL else '다음 문제'
            feedback = f'''
              <div class="feedback" role="status"><strong>{title}</strong>
                <p>정답: {answer} · {escape(result['explanation'])}</p></div>
              <div class="round-actions">{action_button(path + '/next', next_label)}</div>'''
        return f'''
          <div class="stage round">
            <div class="stage-top">
              <span class="meta">문제 {index + 1} / {TOTAL}</span>
              <span class="clock-readout"><span class="clock-icon" aria-hidden="true"></span>{timer}</span>
            </div>
            <div class="round-meter">{meter(left, ROUND_SECONDS, '문제의 남은 시간', result is None)}</div>
            <h2 id="question-title">{escape(question['title'])}</h2>
            <form method="post" action="{path}/answer" class="options" aria-label="답안 선택">
              {"".join(choices)}
            </form>
            {feedback}
          </div>'''

    def hint_panel(self, path, state, now):
        deadline = state['deadline'] - ROUND_SECONDS + HINT_SECONDS
        left = max(0, deadline - now)
        events = state.get('hint_events', [])
        recent = events[0] if events else None
        if left == 0:
            message = HINT_MISS if recent and recent['status'] == 'MISS' else HINT_RETRY
            message = f'<p role="status">{message}</p>'
        else:
            value = recent['value'] if recent and recent['status'] == 'HIT' else '힌트 조회를 누르면 Redis에서 값을 찾아요.'
            message = f'''
              <div class="hint-details" style="--delay:{left:.3f}s">
                <p class="hide-at-end">{escape(value)}</p>
                <p class="show-at-end">{HINT_RETRY}</p>
              </div>'''
        return f'''
          <div class="hint-heading"><h2>Redis 힌트</h2>
            <span class="hint-time">{countdown(left, '만료')}</span>
          </div>
          {meter(left, HINT_SECONDS, '힌트의 남은 시간')}
          {message}
          {action_button(path + '/hint', '힌트 조회', 'hint-button', '↗')}'''

    def event_panel(self, token, events):
        items = [
            '<li><b>SET</b><span>힌트를 저장했어요. '
            f'TTL {HINT_SECONDS}초</span></li>'
        ]
        for event in reversed(events):
            hit = event['status'] == 'HIT'
            tone = 'hit' if hit else 'miss'
            message = '유효한 힌트를 반환했어요.' if hit else 'Redis에 유효한 힌트가 없어요.'
            items.append(f'<li><b class="{tone}">GET · {event["status"]}</b><span>{message}</span></li>')
        return f'<code>quiz:hint:{token}</code><ol class="cache-log">{"".join(items)}</ol>'

    def results(self, results):
        count = sum(result['correct'] for result in results)
        lines = []
        for i, result in enumerate(results, 1):
            label = '시간 초과' if result['timed_out'] else '정답' if result['correct'] else '오답'
            question = escape(QUESTIONS[result['index']]['title'])
            lines.append(f'<li>{i}. {question} · {label}</li>')
        return f'''
          <div class="stage finish">
            <span class="meta">퀴즈 완료</span><h2>오늘의 결과</h2>
            <p class="score">{count} / {TOTAL}</p>
            <ul class="result-list">{"".join(lines)}</ul>
            {action_button('/quiz/start', '다시 풀기', arrow='↻')}
          </div>'''

    def render(self, stage, hint, events, completed=0, index=None, active=False, refresh='', message=''):
        dots = []
        for number in range(TOTAL):
            status = 'done' if number < completed else 'current' if number == index else ''
            dots.append(f'<li class="{status}"></li>')
        return TEMPLATE.substitute(
            stage=stage, hint=hint, events=events, progress=f'{completed} / {TOTAL} 완료',
            dots=''.join(dots), layout='layout playing' if active else 'layout',
            refresh=refresh, message=f'<p class="error" role="alert">{escape(message)}</p>' if message else '',
        )
