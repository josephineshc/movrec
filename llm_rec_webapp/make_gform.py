"""
questionnaire.py 문항으로 구글 설문지를 자동으로 만드는 Apps Script(create_form.gs) 생성
  python make_gform.py  →  create_form.gs
"""
import json
import random

from questionnaire import ATTENTION, ITEMS, SCALE_KO

order = list(ITEMS)
random.Random(42).shuffle(order)                      # 모든 참가자에게 같은 무작위 순서
order.insert(len(order) // 2, ATTENTION)
items = [{"code": c, "text": ko} for c, _, _, _, ko in order]

gs = f"""// 구글 설문지 자동 생성 스크립트
// 사용법: script.google.com → 새 프로젝트 → 이 코드 붙여넣기 → createForm 실행
// 실행 로그에 (1) 설문 편집 링크 (2) SURVEY_URL 값이 출력됨
const ITEMS = {json.dumps(items, ensure_ascii=False, indent=1)};

function createForm() {{
  const form = FormApp.create('영화 추천 시스템 사용 경험 설문');
  form.setDescription('추천 시스템을 사용한 경험에 대해 각 문장에 얼마나 동의하는지 골라 주세요.');
  form.setCollectEmail(false);
  form.setProgressBar(true);

  const idItem = form.addTextItem()
    .setTitle('참가자 번호 (자동 입력됨, 수정하지 마세요)')
    .setRequired(true);

  form.addPageBreakItem().setTitle('설문');
  ITEMS.forEach(function (it) {{
    form.addScaleItem()
      .setTitle(it.text)
      .setHelpText(it.code)               // 응답 CSV에서 문항 코드 확인용 (참가자에게도 작게 보임)
      .setBounds(1, 7)
      .setLabels('{SCALE_KO[0]}', '{SCALE_KO[-1]}')
      .setRequired(true);
  }});
  form.setConfirmationMessage('참여해 주셔서 감사합니다. 이 창을 닫으셔도 됩니다.');

  const prefill = form.createResponse()
    .withItemResponse(idItem.createResponse('PIDPLACEHOLDER'))
    .toPrefilledUrl();
  Logger.log('설문 편집 링크: ' + form.getEditUrl());
  Logger.log('SURVEY_URL 값: ' + prefill.replace('PIDPLACEHOLDER', '{{pid}}'));
}}
"""
open("create_form.gs", "w").write(gs)
print(f"create_form.gs 생성 ({len(items)}문항)")
