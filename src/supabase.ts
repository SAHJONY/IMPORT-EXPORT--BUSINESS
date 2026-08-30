import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || ''
const supabasePublishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || import.meta.env.VITE_SUPABASE_ANON_KEY || ''

export const supabaseConfigured = Boolean(supabaseUrl && supabasePublishableKey)

export const supabase = createClient(
  supabaseUrl || 'https://invalid.local',
  supabasePublishableKey || 'missing-publishable-key',
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      storageKey: 'sahjony.supabase.auth',
    },
  },
)

export async function currentAccessToken(): Promise<string> {
  if (!supabaseConfigured) return ''
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token || ''
}

export async function signOutSupabase(): Promise<void> {
  if (!supabaseConfigured) return
  await supabase.auth.signOut()
}
