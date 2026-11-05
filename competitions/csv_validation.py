import csv
import io
import math


MAX_UPLOAD_BYTES = 5_000_000
MAX_ERRORS = 30
FEATURES = [
    'hotel', 'reserved_room_type', 'meal', 'arrival_month', 'arrival_weekday', 'lead_time',
    'stays_in_week_nights', 'stays_in_weekend_nights', 'adults', 'children', 'babies',
    'market_segment', 'distribution_channel',
]
TEST_COLUMNS = ['reservation_id', *FEATURES]


class ArenaError(Exception):
    def __init__(self, code, message, status=400, errors=None):
        self.code = code
        self.message = message
        self.status = status
        self.errors = errors or []
        super().__init__(message)


def validate_submission(content, expected_ids):
    if len(content) > MAX_UPLOAD_BYTES:
        raise ArenaError('FILE_TOO_LARGE', 'CSV 파일은 5MB(5,000,000바이트) 이하여야 합니다.', 413)
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ArenaError('CSV_ENCODING', 'UTF-8 또는 UTF-8 BOM 형식의 CSV로 저장해 주세요.') from None
    if '\x00' in text:
        raise ArenaError('CSV_FORMAT', 'CSV에 사용할 수 없는 문자가 있습니다. UTF-8 CSV로 다시 저장해 주세요.')
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    predictions, seen, errors = {}, set(), []
    counts = {'duplicate': 0, 'unknown': 0, 'invalid': 0}

    def error(code, message, record=None):
        if len(errors) < MAX_ERRORS:
            errors.append({'code': code, 'message': message, 'record': record})

    try:
        header = next(reader, [])
        if len(header) != 2 or set(header) != {'reservation_id', 'adr'}:
            raise ArenaError('CSV_HEADERS', '필수 헤더는 reservation_id, adr 두 개입니다. 추가 열과 중복 헤더는 사용할 수 없습니다.')
        id_col, value_col = header.index('reservation_id'), header.index('adr')
        for record, row in enumerate(reader, start=2):
            if not row:
                continue
            if len(row) != 2:
                counts['invalid'] += 1
                error('COLUMN_COUNT', f'CSV 레코드 {record}의 열 개수가 2개가 아닙니다.', record)
                continue
            rid, raw = row[id_col], row[value_col]
            if rid in seen:
                counts['duplicate'] += 1
                error('DUPLICATE_ID', f'CSV 레코드 {record}의 ID가 중복되었습니다.', record)
            seen.add(rid)
            if rid not in expected_ids:
                counts['unknown'] += 1
                error('UNKNOWN_ID', f'CSV 레코드 {record}의 ID가 Test에 없습니다. ID 문자열을 그대로 사용해 주세요.', record)
            try:
                value = float(raw) if raw.strip() else None
            except (ValueError, OverflowError):
                value = None
            if value is None or not math.isfinite(value):
                counts['invalid'] += 1
                error('INVALID_PREDICTION', f'CSV 레코드 {record}의 adr은 비어 있지 않은 유한한 숫자여야 합니다. NaN과 Infinity는 사용할 수 없습니다.', record)
            else:
                predictions[rid] = value
    except csv.Error:
        raise ArenaError('CSV_FORMAT', f'CSV의 {reader.line_num}번째 줄 부근을 읽을 수 없습니다. 인용 문자와 열 구분을 확인해 주세요.') from None
    missing = len(expected_ids - seen)
    if missing:
        error('MISSING_IDS', f'Test ID {missing:,}개가 누락되었습니다.')
    if errors:
        message = (
            f'CSV를 확인해 주세요. 누락 ID {missing:,}개, 중복 ID {counts["duplicate"]:,}개, '
            f'Test에 없는 ID {counts["unknown"]:,}개, 잘못된 행·예측값 {counts["invalid"]:,}개입니다. '
            '정상 접수되지 않아 제출 횟수는 차감되지 않았습니다.'
        )
        raise ArenaError('CSV_VALIDATION', message, errors=errors)
    return predictions


def rmse(actual, predicted):
    if not actual or len(actual) != len(predicted):
        raise ValueError('Evaluation rows do not match')
    scale = max(max(map(abs, actual)), max(map(abs, predicted)))
    if scale == 0:
        return 0.0
    # Scale before squaring so even very large finite predictions remain scoreable.
    return scale * math.sqrt(math.fsum((a / scale - p / scale) ** 2 for a, p in zip(actual, predicted)) / len(actual))
