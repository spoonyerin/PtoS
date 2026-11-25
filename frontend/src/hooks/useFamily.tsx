import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { FamilyError, familyApi, type FamilyReplyChoice, type FamilyRequestItem, type FamilySummary } from '../api/family'
import { clearDeviceToken, readDeviceToken, saveDeviceToken } from '../family/deviceToken'
import { createPushSubscription, removePushSubscription } from '../family/push'
import { useFamilyStatus } from './useServiceStatus'

// 가족 보호(발표 시연 한정) 상태. 서버가 꺼져 있으면 아무 요청도 보내지 않는다.
// 이 기기를 가족 보호에 쓴 적이 없으면(열쇠 없음) 홈에서도 요청하지 않는다.

type Api = typeof familyApi
export type FamilyActions = {
  setPremium: (active: boolean) => Promise<FamilySummary>
  createInvite: (...args: Parameters<Api['createInvite']>) => ReturnType<Api['createInvite']>
  previewInvite: (token: string) => ReturnType<Api['previewInvite']>
  acceptInvite: (token: string, name: string) => Promise<FamilySummary>
  removeLink: (id: string) => Promise<FamilySummary>
  setAutoAlert: (linkId: string | null) => Promise<FamilySummary>
  sendRequests: Api['sendRequests']
  listRequests: (box: 'sent' | 'received') => Promise<FamilyRequestItem[]>
  getRequest: (id: string) => Promise<FamilyRequestItem>
  reply: (id: string, choice: FamilyReplyChoice, text?: string) => Promise<FamilyRequestItem>
}

type FamilyContextValue = {
  actions: FamilyActions
  available: boolean
  summary: FamilySummary | null
  loading: boolean
  refresh: () => Promise<FamilySummary | null>
  ensureDevice: () => Promise<void>
  update: (next: FamilySummary) => void
  enablePush: () => Promise<FamilySummary>
  disablePush: () => Promise<FamilySummary>
  forgetDevice: () => Promise<void>
}

const FamilyContext = createContext<FamilyContextValue | null>(null)

const off = async (): Promise<never> => { throw new FamilyError('FAMILY_OFF', '가족 보호 기능이 이 서버에서 꺼져 있어요.') }
// FamilyProvider 밖(단위 테스트 등)에서는 꺼진 상태로 동작한다.
const OFF: FamilyContextValue = {
  available: false, summary: null, loading: false, refresh: async () => null, ensureDevice: off, update: () => undefined,
  enablePush: off, disablePush: off, forgetDevice: async () => undefined,
  actions: { setPremium: off, createInvite: off, previewInvite: off, acceptInvite: off, removeLink: off, setAutoAlert: off,
    sendRequests: off, listRequests: off, getRequest: off, reply: off },
}

export function useFamily(): FamilyContextValue {
  return useContext(FamilyContext) ?? OFF
}

export function FamilyProvider({ children }: { children: ReactNode }) {
  const status = useFamilyStatus()
  const available = status.family === 'live'
  const [summary, setSummary] = useState<FamilySummary | null>(null)
  const [loading, setLoading] = useState(false)
  const registering = useRef<Promise<void> | null>(null)

  const refresh = useCallback(async () => {
    if (!available || !readDeviceToken()) return null
    setLoading(true)
    try {
      const next = await familyApi.summary()
      setSummary(next)
      return next
    } catch (error) {
      if (error instanceof FamilyError && error.code === 'DEVICE_REQUIRED') setSummary(null)
      return null
    } finally {
      setLoading(false)
    }
  }, [available])

  const ensureDevice = useCallback(async () => {
    if (!available) throw new FamilyError('FAMILY_OFF', '가족 보호 기능이 이 서버에서 꺼져 있어요.')
    if (readDeviceToken()) return
    registering.current ??= familyApi.registerDevice()
      .then(({ device_token }) => saveDeviceToken(device_token))
      .finally(() => { registering.current = null })
    await registering.current
  }, [available])

  useEffect(() => {
    if (!available) return
    void refresh()
    // 화면에 돌아올 때와 열려 있는 동안 가끔 새 요청·의견을 확인한다.
    const onVisible = () => { if (document.visibilityState === 'visible') void refresh() }
    document.addEventListener('visibilitychange', onVisible)
    const timer = window.setInterval(onVisible, 20_000)
    return () => { document.removeEventListener('visibilitychange', onVisible); window.clearInterval(timer) }
  }, [available, refresh])

  const enablePush = useCallback(async () => {
    await ensureDevice()
    const { public_key } = await familyApi.pushKey()
    if (!public_key) throw new FamilyError('PUSH_OFF', '이 서버에서는 알림을 보낼 수 없어요.')
    const subscription = await createPushSubscription(public_key)
    const next = await familyApi.subscribePush(subscription)
    setSummary(next)
    return next
  }, [ensureDevice])

  const disablePush = useCallback(async () => {
    const endpoint = await removePushSubscription()
    const next = await familyApi.removePush(endpoint)
    setSummary(next)
    return next
  }, [])

  const forgetDevice = useCallback(async () => {
    await removePushSubscription().catch(() => null)
    await familyApi.deleteDevice().catch(() => undefined)
    clearDeviceToken()
    setSummary(null)
  }, [])

  const actions = useMemo<FamilyActions>(() => ({
    setPremium: async (active) => { await ensureDevice(); const next = await familyApi.setPremium(active); setSummary(next); return next },
    createInvite: async (name, relation) => {
      await ensureDevice()
      const invite = await familyApi.createInvite(name, relation)
      void refresh()
      return invite
    },
    previewInvite: async (token) => { await ensureDevice(); return familyApi.previewInvite(token) },
    acceptInvite: async (token, name) => { await ensureDevice(); const next = await familyApi.acceptInvite(token, name); setSummary(next); return next },
    removeLink: async (id) => { const next = await familyApi.removeLink(id); setSummary(next); return next },
    setAutoAlert: async (linkId) => { const next = await familyApi.setAutoAlert(linkId); setSummary(next); return next },
    sendRequests: (body) => familyApi.sendRequests(body),
    listRequests: (box) => familyApi.listRequests(box).then(({ items }) => items),
    getRequest: async (id) => { const item = await familyApi.getRequest(id); void refresh(); return item },
    reply: async (id, choice, text) => { const item = await familyApi.reply(id, choice, text); void refresh(); return item },
  }), [ensureDevice, refresh])

  const value = useMemo<FamilyContextValue>(() => ({
    available, summary, loading, refresh, ensureDevice, update: setSummary, enablePush, disablePush, forgetDevice, actions,
  }), [available, summary, loading, refresh, ensureDevice, enablePush, disablePush, forgetDevice, actions])

  return <FamilyContext.Provider value={value}>{children}</FamilyContext.Provider>
}
