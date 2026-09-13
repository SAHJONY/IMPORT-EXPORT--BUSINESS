/** Private owner datasets must never fall back to an unauthenticated static file. */
export async function ownerDataFetch(path: string): Promise<Response> {
  const token = sessionStorage.getItem('sahjony.owner.token');
  if (!token) {
    location.replace('/owner-login');
    throw new Error('Owner sign-in required');
  }
  const response = await fetch(path, {cache: 'no-store', headers: {'X-Role': 'owner', Authorization: `Bearer ${token}`}});
  if (response.status === 401 || response.status === 403) {
    sessionStorage.removeItem('sahjony.owner.token');
    location.replace('/owner-login');
    throw new Error('Owner session expired');
  }
  if (!response.ok) throw new Error(`Unable to load owner records (${response.status})`);
  return response;
}
