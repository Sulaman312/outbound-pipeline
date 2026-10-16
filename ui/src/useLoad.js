// Load data for a page: {data, error, loading, reload}. Reloads when `deps` change.
import { useCallback, useEffect, useState } from "react";

export function useLoad(load, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const run = useCallback(load, deps);

  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true }));
    return run().then(
      (data) => setState({ data, error: null, loading: false }),
      (error) => setState({ data: null, error: error.message, loading: false }),
    );
  }, [run]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { ...state, reload };
}
