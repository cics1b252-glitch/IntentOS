/** Always releases the conversation UI after success, rejection, timeout or bridge exit. */
export async function runRecoverable(operation, handlers = {}) {
  handlers.onStart?.();
  try {
    const result = await operation();
    handlers.onResult?.(result);
    return result;
  } catch (error) {
    handlers.onError?.(error);
    return null;
  } finally {
    handlers.onFinally?.();
  }
}
