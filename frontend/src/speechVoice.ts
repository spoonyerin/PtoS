// 이름과 서비스 유형은 음질을 추정하는 단서이며 실제 품질을 보장하지 않습니다.
export function selectKoreanVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | undefined {
  const score = (voice: SpeechSynthesisVoice) =>
    (/natural|neural|online|wavenet|premium|enhanced|siri/i.test(voice.name) ? 4 : 0)
    + (voice.localService === false ? 2 : 0)
    + (voice.lang.toLowerCase() === 'ko-kr' ? 1 : 0)

  // 같은 점수라면 브라우저가 제공한 순서를 유지합니다.
  return voices.filter(voice => /^ko(?:-|_|$)/i.test(voice.lang))
    .reduce<SpeechSynthesisVoice | undefined>((best, voice) =>
      !best || score(voice) > score(best) ? voice : best, undefined)
}
