"""Timed quiz rounds whose hint values expire in MiniRedis."""

from uuid import uuid4

from cache import MiniRedis


QUESTIONS = (
    {
        'title': '캐시에서 유효한 값을 찾았다면?',
        'options': ('캐시 HIT', '캐시 MISS', '캐시 우회'),
        'answer': 0,
        'hint': '같은 키로 저장해 둔 결과를 바로 재사용할 수 있어요.',
        'why': 'HIT는 유효한 결과를 캐시에서 찾아 재사용했다는 뜻이에요.',
    },
    {
        'title': 'TTL이 지난 키를 조회하면 어떤 결과가 나올까요?',
        'options': ('기존 값 반환', '값을 찾지 못함', 'TTL 자동 연장'),
        'answer': 1,
        'hint': '이 키는 Redis에서 정한 유효 기간을 넘겼어요.',
        'why': 'TTL이 지난 값은 만료돼요. Mini Redis는 조회할 때 만료를 확인하고 값을 제거해요.',
    },
    {
        'title': 'DB의 가격을 바꿀 때, 언제 캐시를 지우는 게 좋을까요?',
        'options': ('DB 저장 전에', 'DB 저장과 관계없이', 'DB 저장이 성공한 뒤에'),
        'answer': 2,
        'hint': '너무 일찍 지우면 누군가 이전 가격으로 캐시를 다시 채울 수 있어요.',
        'why': 'DB 저장이 성공한 뒤 이전 목록의 캐시를 지우면, 다음 조회에서 새 가격을 읽어 채울 수 있어요.',
    },
    {
        'title': '가격순 목록과 최신순 목록을 어떻게 캐싱할까요?',
        'options': ('정렬 방식별로 키를 나눠요', '두 목록에 항상 같은 키를 써요', '매번 아무 키나 골라요'),
        'answer': 0,
        'hint': '같은 상품이어도 정렬 방식에 따라 목록의 순서가 달라져요.',
        'why': '조회 결과를 바꾸는 조건을 캐시 키에 포함하면 서로 다른 목록을 구분할 수 있어요.',
    },
    {
        'title': '캐시 MISS가 자주 나면 어떤 비용이 생길까요?',
        'options': ('DB 조회가 항상 사라져요', 'TTL이 더 길어져요', 'DB를 읽고 캐시도 확인하고 채워야 해요'),
        'answer': 2,
        'hint': '재사용할 결과가 없으면 원본에서 새로 읽어야 해요.',
        'why': 'MISS가 나면 DB 조회에 캐시 확인과 저장 작업이 더해져요. 같은 결과의 HIT가 많을수록 이 비용을 만회하기 쉬워요.',
    },
)

ROUND_SECONDS = 25
HINT_SECONDS = 10
RESULT_SECONDS = 90


class Quiz:
    def __init__(self, clock):
        self.cache = MiniRedis(clock)
        self.clock = clock

    def start(self, index, history=()):
        if type(index) is not int or not 0 <= index < len(QUESTIONS):
            raise ValueError('Invalid question index')
        question = QUESTIONS[index]
        token = uuid4().hex
        hint_key = f'quiz:hint:{token}'
        with self.cache.lock:
            self.cache.sweep()
            deadline = self.clock() + ROUND_SECONDS
            self.save_round(token, {'index': index, 'deadline': deadline, 'history': list(history)})
            self.cache.set(hint_key, question['hint'], HINT_SECONDS)
        return {
            'token': token, 'index': index, 'total': len(QUESTIONS),
            'title': question['title'], 'options': question['options'],
            'round_seconds': ROUND_SECONDS, 'hint_seconds': HINT_SECONDS,
            'key': hint_key,
        }

    def hint(self, token):
        result = self.cache.get(f'quiz:hint:{token}')
        return {'status': 'HIT' if result['found'] else 'MISS', 'value': result['value']}

    def get_round(self, token):
        record = self.cache.get(f'quiz:round:{token}')
        if not record['found']:
            raise LookupError('Round expired. Start a new quiz.')
        return record['value']

    def save_round(self, token, state):
        ttl = max(0, state['deadline'] + RESULT_SECONDS - self.clock())
        self.cache.set(f'quiz:round:{token}', state, ttl)

    def answer(self, token, choice):
        with self.cache.lock:
            state = self.get_round(token)
            if 'result' in state:
                return state['result']
            question = QUESTIONS[state['index']]
            if choice is not None and (type(choice) is not int or not 0 <= choice < len(question['options'])):
                raise ValueError('Invalid answer choice')
            answered_at = self.clock()
            timed_out = answered_at >= state['deadline']
            if choice is None and not timed_out:
                raise ValueError('The round is still active')
            result = {
                'correct': not timed_out and choice == question['answer'],
                'timed_out': timed_out,
                'selected': None if timed_out else choice,
                'answer': question['answer'],
                'explanation': question['why'],
            }
            self.save_round(token, {**state, 'result': result, 'answered_at': answered_at})
            return result
