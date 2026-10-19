export const isMock = new URLSearchParams(location.search).get('mock') === '1';

// Reads are quick; POSTs may run the privacy pipeline on a slow fallback model (20-60 s).
export async function api(path, { method = 'GET', body, timeout = method === 'GET' ? 15000 : 180000 } = {}) {
  if (isMock) {
    const { mockRequest } = await import('./mock.js');
    return mockRequest(path, method, body);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, {
      method,
      headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: controller.signal,
      cache: 'no-store',
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = typeof data?.detail === 'string' ? data.detail : '';
      throw new Error(detail || `เชื่อมต่อระบบไม่สำเร็จ (${response.status}) กรุณาลองอีกครั้ง`);
    }
    return data ?? {};
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('ระบบตอบกลับช้า กรุณาลองอีกครั้ง');
    if (error instanceof TypeError) throw new Error('ยังเชื่อมต่อระบบไม่ได้ กรุณาตรวจสอบการเชื่อมต่อแล้วลองอีกครั้ง');
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export const post = (path, body = {}) => api(path, { method: 'POST', body });
