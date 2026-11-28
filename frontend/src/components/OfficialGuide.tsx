import { useEffect, useRef, useState } from 'react'
import { Icon } from './Icons'
const categories = [
  ['은행·카드사', '대출 및 결제 승인 문자 확인 방법', 'risk-impersonation.svg'],
  ['택배사·우체국', '주소 재입력·반송문자 확인 방법', 'icon-box.svg'],
  ['경찰·검찰', '출석요구·계좌 안전 조치 확인 방법', 'icon-police.svg'],
  ['금융감독원', '공식 신고·상담 창구 안내', 'icon-investigation.svg'],
  ['통신사·정부지원금', '환급·지원금 안내문자 확인 방법', 'icon=call.svg'],
  ['기타', '기타 자주 나타나는 사기 패턴', null],
] as const
const carriers = ['우체국 택배', 'CJ대한통운', '한진택배', '롯데택배', '로젠택배', 'CU 편의점택배', 'GS25 편의점택배', '경동택배']
const guidance = [
  ['문자에 포함된 의심스러운 링크 클릭 금지', '공식 홈페이지나 앱에 직접 접속해서 정보를 확인하세요.'],
  ['앱 설치 요구에 응하지 않기', '출처를 확인할 수 없는 앱이나 APK를 설치하지 마세요.'],
  ['개인정보를 입력하기 전에 출처 확인하기', '배송 확인을 이유로 민감한 정보를 요구하면 먼저 공식 경로로 확인하세요.'],
  ['발신번호만 믿지 않기', '표시된 번호만으로 실제 발신자를 확인할 수는 없어요.'],
  ['의심스러운 배송은 직접 확인하기', '문자 속 링크 대신 평소 사용하는 공식 앱이나 홈페이지에서 확인하세요.'],
]
export function OfficialGuide({ onBack }: { onBack: () => void }) {
  const [category, setCategory] = useState<string | null>(null)
  const [carrier, setCarrier] = useState<string | null>(null)
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [selectedCarrier, setSelectedCarrier] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [added, setAdded] = useState(false)
  const dialog = useRef<HTMLDialogElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const title = carrier ?? category ?? '공식 확인 가이드'
  useEffect(() => { heading.current?.focus(); window.scrollTo(0, 0) }, [title])
  function back() { if (carrier) setCarrier(null); else if (category) setCategory(null); else onBack() }
  return <>
    <header className="page-header guide-header"><button className="icon-button" aria-label={category ? '이전 가이드로 돌아가기' : '가족 보호로 돌아가기'} onClick={back}><Icon name="back" /></button><h1 ref={heading} tabIndex={-1}>{title}</h1></header>
    <main id="main" tabIndex={-1} className="official-guide-main">
      {!category ? <>
        <label className="sr-only" htmlFor="guide-search">기관·은행·택배사 검색하기</label><input id="guide-search" className="guide-search" placeholder="기관·은행·택배사 검색하기" value={search} onChange={e => setSearch(e.target.value)} />
        <h2>어떤 분야인가요?</h2><div className="guide-category-grid">{categories.filter(([name, description]) => `${name} ${description} ${name === '택배사·우체국' ? carriers.join(' ') : ''}`.includes(search.trim())).map(([name, description, asset]) => <button key={name} aria-pressed={selectedCategory === name} onClick={() => { setSelectedCategory(name); setCategory(name); setSearch('') }}><span className="guide-category-top"><span className="guide-category-icon">{asset ? <span style={{ maskImage: `url('/assets/${asset}')`, WebkitMaskImage: `url('/assets/${asset}')` }} /> : '•••'}</span><Icon name="chevron" /></span><strong>{name}</strong><small>{description}</small></button>)}</div>
        {search && !categories.some(([name, desc]) => `${name} ${desc} ${name === '택배사·우체국' ? carriers.join(' ') : ''}`.includes(search.trim())) && <p>일치하는 분야가 없어요. 기관 추가를 요청해 주세요.</p>}
        <p className="guide-add">찾는 기관이 없나요? <button onClick={() => { setAdded(false); dialog.current?.showModal() }}>추가 요청하기</button></p>
      </> : category === '택배사·우체국' && !carrier ? <><p className="guide-help">확인하고 싶은 택배사를 선택하세요.</p><div className="guide-carriers">{carriers.map(name => <button key={name} aria-pressed={selectedCarrier === name} onClick={() => { setSelectedCarrier(name); setCarrier(name) }}>{name}<Icon name="chevron" /></button>)}</div></> : <>
        <h2 className="guide-detail-title">{category === '택배사·우체국' ? <>의심되는 배송 문자,<br />이렇게 대응하세요</> : <>의심되는 안내 문자,<br />이렇게 확인하세요</>}</h2>
        <ul className="guide-advice">{guidance.map(([label, detail]) => <li key={label}><span className="guide-check" aria-hidden="true" /><div><strong>{category === '택배사·우체국' ? label : label.replace('배송은', '안내는')}</strong><p>{category === '택배사·우체국' ? detail : detail.replace('배송 확인', '본인 확인')}</p></div></li>)}</ul>
        <h2 className="guide-links-title">공식 경로로 바로 확인하기</h2>
        {carrier === '우체국 택배' ? <div className="guide-official-links"><a href="https://www.epost.go.kr/" target="_blank" rel="noopener noreferrer"><span><strong>인터넷우체국 배송조회</strong><small>www.epost.go.kr</small></span><Icon name="chevron" /></a><a href="tel:15881300"><span><strong>우편고객센터 1588-1300</strong><small>전화로 배송 사실 직접 확인하기</small></span><Icon name="chevron" /></a></div> : <p className="guide-help">{carrier ?? category}의 공식 경로는 확인 후 등록할 예정입니다. 문자에 적힌 연락처 대신 평소 알고 있던 공식 홈페이지에서 확인해 주세요.</p>}
      </>}
    </main>
    <dialog ref={dialog} aria-labelledby="guide-add-title" className="guide-add-dialog"><form onSubmit={e => { e.preventDefault(); setAdded(true) }}><h2 id="guide-add-title">기관 추가 요청</h2>{added ? <p role="status">추가 요청 화면을 확인했어요. 실제 접수 기능은 준비 중입니다.</p> : <><label>기관 이름<input required maxLength={40} placeholder="기관 이름 입력" /></label><p>개발용 미리보기이며 실제 요청은 전송하지 않습니다.</p><button className="primary-button" type="submit">요청하기</button></>}<button type="button" className="family-outline-button" onClick={() => dialog.current?.close()}>닫기</button></form></dialog>
  </>
}
