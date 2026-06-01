-- ============================================================
-- board.form_type 도입 마이그레이션 (Supabase 콘솔에서 실행)
--
-- 대응 Django 마이그레이션:
--   0038_board_form_type            (컬럼 추가)
--   0039_backfill_board_form_type   (기존 값 백필)
--
-- form_type 값: 0=NONE(일반), 1=ABSENCE(결석사유서), 2=FEEDBACK(에러/피드백 제보)
-- board_type(접근 권한)과는 별개로 "작성 폼 종류"만 나타낸다.
--
-- 전체를 한 트랜잭션으로 실행하면 중간 실패 시 자동 롤백된다.
-- ============================================================

BEGIN;

-- 1) 컬럼 추가 (Django AddField IntegerField(default=0) 와 동일)
ALTER TABLE "board" ADD COLUMN "form_type" integer DEFAULT 0 NOT NULL;
ALTER TABLE "board" ALTER COLUMN "form_type" DROP DEFAULT;

-- 2) 기존 게시판 백필 (0039 data migration 과 동일한 휴리스틱, 순서 중요)
--    먼저 에러/피드백/제보 게시판을 FEEDBACK(2)로,
UPDATE "board" SET "form_type" = 2
 WHERE "name" LIKE '%에러%' OR "name" LIKE '%피드백%' OR "name" LIKE '%제보%';

--    그다음 아직 NONE인 것 중 사유서(board_type=3 또는 이름)에 ABSENCE(1)를 부여
UPDATE "board" SET "form_type" = 1
 WHERE "form_type" = 0 AND ("board_type" = 3 OR "name" LIKE '%사유서%');

-- 3) Django 마이그레이션 적용 기록 (이후 서버에서 migrate 실행 시 중복 적용 방지)
INSERT INTO "django_migrations" ("app", "name", "applied") VALUES
  ('boards', '0038_board_form_type', NOW()),
  ('boards', '0039_backfill_board_form_type', NOW());

COMMIT;

-- ============================================================
-- 검증: 백필 결과 확인 (실행 후 form_type 값이 의도대로인지 눈으로 확인)
--   SELECT id, name, board_type, form_type FROM "board" ORDER BY board_type, id;
-- ============================================================
