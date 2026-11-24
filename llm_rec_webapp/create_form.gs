// 구글 설문지 자동 생성 스크립트
// 사용법: script.google.com → 새 프로젝트 → 이 코드 붙여넣기 → createForm 실행
// 실행 로그에 (1) 설문 편집 링크 (2) SURVEY_URL 값이 출력됨
const ITEMS = [
 {
  "code": "PQ4",
  "text": "추천된 영화들은 적절했다"
 },
 {
  "code": "PD4",
  "text": "추천 목록은 폭넓은 취향에 맞는다"
 },
 {
  "code": "PQ5",
  "text": "시스템이 별로인 영화를 너무 많이 추천했다"
 },
 {
  "code": "CD4",
  "text": "영화를 고르기 쉬웠다"
 },
 {
  "code": "SS3",
  "text": "이 추천 시스템을 쓰면 더 좋은 영화를 찾을 수 있다"
 },
 {
  "code": "CS7",
  "text": "내가 고른 영화보다 다른 영화를 보고 싶다"
 },
 {
  "code": "SS5",
  "text": "이 시스템 덕분에 내가 고를 수 있는 선택지를 더 잘 알게 된다"
 },
 {
  "code": "CD3",
  "text": "결정하는 일이 버겁게 느껴졌다"
 },
 {
  "code": "PD5",
  "text": "추천된 영화들은 여러 다양한 장르였다"
 },
 {
  "code": "PTC6",
  "text": "추천된 영화들은 여러 면에서 나에게 잘 맞았다"
 },
 {
  "code": "TDO4",
  "text": "추천된 영화들이 너무 달라서 비교하기 어려웠다"
 },
 {
  "code": "PQ6",
  "text": "추천된 영화 중 마음에 드는 것이 하나도 없었다"
 },
 {
  "code": "PTC2",
  "text": "추천된 영화들은 나의 다양한 영화 취향을 반영하지 못했다"
 },
 {
  "code": "TDO3",
  "text": "추천된 영화들을 서로 비교하기 쉬웠다"
 },
 {
  "code": "CS1",
  "text": "최종 추천 목록에서 내가 고른 영화가 마음에 든다"
 },
 {
  "code": "CD2",
  "text": "결정하기 전에 마음을 여러 번 바꿨다"
 },
 {
  "code": "SS1",
  "text": "이 추천 시스템을 사용하는 것은 즐거운 경험이다"
 },
 {
  "code": "SS2",
  "text": "이 시스템을 다른 사람에게 추천하겠다"
 },
 {
  "code": "PTC5",
  "text": "추천 목록은 나의 다양한 선호에 맞았다"
 },
 {
  "code": "CS2",
  "text": "내가 고른 영화는 내 취향에 맞는다"
 },
 {
  "code": "CD1",
  "text": "목록의 여러 영화 사이에서 고민했다"
 },
 {
  "code": "ATT1",
  "text": "이 문항에는 '약간 그렇다'를 선택해 주세요"
 },
 {
  "code": "TDO2",
  "text": "추천된 영화들을 비교하는 것은 전혀 다른 것끼리 비교하는 느낌이었다"
 },
 {
  "code": "PTC1",
  "text": "추천 시스템은 내가 관심을 가질 만한 것들을 모두 고려했다"
 },
 {
  "code": "SS4",
  "text": "이 시스템은 쓸모없다"
 },
 {
  "code": "PTC3",
  "text": "추천 시스템은 내 관심사 중 일부만 겨냥한 것 같았다"
 },
 {
  "code": "TDO1",
  "text": "추천된 영화들의 여러 측면을 비교하는 데 많은 노력이 들었다"
 },
 {
  "code": "CS5",
  "text": "추천된 영화 중 가장 좋은 영화를 고른 것 같다"
 },
 {
  "code": "SS7",
  "text": "이 시스템은 나에게 실질적인 도움이 되지 않는다"
 },
 {
  "code": "PTC7",
  "text": "추천 시스템은 나를 특정 유형의 관객으로 고정해서 본 것 같았다"
 },
 {
  "code": "PTC4",
  "text": "추천 시스템은 나를 단면적인 사람으로 취급했다"
 },
 {
  "code": "PD1",
  "text": "최종 추천 목록의 영화들은 모두 서로 비슷했다"
 },
 {
  "code": "PD3",
  "text": "추천된 영화 대부분이 같은 장르였다"
 },
 {
  "code": "CD5",
  "text": "영화들을 비교하는 데 많은 노력이 들었다"
 },
 {
  "code": "PD6",
  "text": "추천에는 다양한 영화가 많이 담겨 있었다"
 },
 {
  "code": "PQ1",
  "text": "추천 시스템이 추천한 영화들이 마음에 들었다"
 },
 {
  "code": "PQ3",
  "text": "추천된 영화들은 내 취향에 맞았다"
 },
 {
  "code": "CS3",
  "text": "내가 고른 영화를 다른 사람이나 친구에게 추천하겠다"
 },
 {
  "code": "CS4",
  "text": "내가 고른 영화가 기대된다"
 },
 {
  "code": "CS6",
  "text": "추천된 영화 중 내가 고른 것보다 나은 영화가 여러 편 있다"
 },
 {
  "code": "PD2",
  "text": "추천 목록에 서로 비슷한 영화는 하나도 없었다"
 },
 {
  "code": "PQ2",
  "text": "추천된 영화들이 끌렸다"
 },
 {
  "code": "SS6",
  "text": "이 시스템을 쓰면 더 나은 선택을 한다"
 }
];

function createForm() {
  const form = FormApp.create('영화 추천 시스템 사용 경험 설문');
  form.setDescription('추천 시스템을 사용한 경험에 대해 각 문장에 얼마나 동의하는지 골라 주세요.');
  form.setCollectEmail(false);
  form.setProgressBar(true);

  const idItem = form.addTextItem()
    .setTitle('참가자 번호 (자동 입력됨, 수정하지 마세요)')
    .setRequired(true);

  form.addPageBreakItem().setTitle('설문');
  ITEMS.forEach(function (it) {
    form.addScaleItem()
      .setTitle(it.text)
      .setHelpText(it.code)               // 응답 CSV에서 문항 코드 확인용 (참가자에게도 작게 보임)
      .setBounds(1, 7)
      .setLabels('전혀 그렇지 않다', '매우 그렇다')
      .setRequired(true);
  });
  form.setConfirmationMessage('참여해 주셔서 감사합니다. 이 창을 닫으셔도 됩니다.');

  const prefill = form.createResponse()
    .withItemResponse(idItem.createResponse('PIDPLACEHOLDER'))
    .toPrefilledUrl();
  Logger.log('설문 편집 링크: ' + form.getEditUrl());
  Logger.log('SURVEY_URL 값: ' + prefill.replace('PIDPLACEHOLDER', '{pid}'));
}
