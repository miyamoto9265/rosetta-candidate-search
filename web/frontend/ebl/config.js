window.ROSETTA_SEARCH_CONFIG = (function () {
  const host = window.location.hostname;
  const local = host === "127.0.0.1" || host === "localhost";
  return {
    // Local server serves /candidates-ebl on the same origin.
    // Production uses API Gateway.
    apiBaseUrl: local
      ? window.location.origin
      : "https://zj7cl034xe.execute-api.ap-northeast-1.amazonaws.com",
    candidatesPath: "/candidates-ebl",
  };
})();
