import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { FamilyShare } from './FamilyShare'
import { shareFixture } from '../test/shareFixture'
import { createFamilyModel } from '../familyModel'
const share = vi.fn(), copy = vi.fn()
const props = { result: shareFixture(), members: createFamilyModel().members, onBack: vi.fn(), onHome: vi.fn(), onConnect: vi.fn() }
beforeEach(() => {
  share.mockReset().mockResolvedValue(undefined); copy.mockReset().mockResolvedValue(undefined)
  vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal('scrollTo', vi.fn())
  vi.stubGlobal('navigator', { share, canShare: () => true, clipboard: { writeText: copy } })
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute('open', '') } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute('open') } })
})
afterEach(() => { cleanup(); Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal'); Reflect.deleteProperty(HTMLDialogElement.prototype, 'close'); vi.restoreAllMocks(); vi.unstubAllGlobals() })
test('링크 발급 전에는 텍스트로 우회 전송하지 않는다', () => {
  render(<FamilyShare {...props} />)
  fireEvent.click(screen.getByRole('button', { name: '공유하기' }))
  expect(screen.getByRole('button', { name: '공유할 앱 선택' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '링크 복사하기' })).toBeDisabled()
  expect(share).not.toHaveBeenCalled(); expect(copy).not.toHaveBeenCalled()
})
test.each([false, true])('발급된 링크만 공유/복사하고 원문·본문을 전달하지 않는다(copy=%s)', async copying => {
  const url = 'https://example.invalid/family/share/test-token'
  render(<FamilyShare {...props} shareUrl={url} />)
  fireEvent.click(screen.getByRole('button', { name: '공유하기' }))
  fireEvent.click(screen.getByRole('button', { name: copying ? '링크 복사하기' : '공유할 앱 선택' }))
  await waitFor(() => expect(copying ? copy : share).toHaveBeenCalledOnce())
  if (copying) expect(copy).toHaveBeenCalledWith(url)
  else expect(share).toHaveBeenCalledWith({ title: 'PtoS 분석 결과', url })
  await waitFor(() => expect(screen.queryByRole('button', { name: '모의 공유 상태 보기' })).not.toBeInTheDocument())
  expect(screen.getByText('가족 확인 여부는 알 수 없어요', { exact: true })).toBeVisible()
})
