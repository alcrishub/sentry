import {useCallback, useEffect, useState} from 'react';

import sessionStorageWrapper from 'sentry/utils/sessionStorage';

const isBrowser = typeof window !== 'undefined';

function readStorageValue<T>(key, initialValue: T) {
  const value = sessionStorage.getItem(key);

  // We check for 'undefined' because the value may have
  // previously been serialized as 'undefined'. This should no longer
  // happen, but want to handle it gracefully.
  if (value === null || value === 'undefined') {
    return initialValue;
  }

  // Try parse storage value.
  try {
    return JSON.parse(value);
  } catch {
    // If parsing fails, return initial value.
    return initialValue;
  }
}

function useSessionStorage<T>(
  key: string,
  initialValue?: T
): [T | undefined, (value: T | undefined) => void, () => void] {
  const [state, setState] = useState<T | undefined>(() =>
    readStorageValue(key, initialValue)
  );

  useEffect(() => {
    setState(readStorageValue(key, initialValue));
    // We want to re-initialized the storage value only when the key changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const wrappedSetState = useCallback(
    (value: T | undefined) => {
      setState(value);

      try {
        sessionStorageWrapper.setItem(key, JSON.stringify(value));
      } catch {
        // Best effort and just update the in-memory value.
      }
    },
    [key]
  );

  const removeItem = useCallback(() => {
    setState(undefined);
    sessionStorageWrapper.removeItem(key);
  }, [key]);

  if (!isBrowser) {
    return [initialValue, () => {}, () => {}];
  }

  return [state, wrappedSetState, removeItem];
}

export default useSessionStorage;
