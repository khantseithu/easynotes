// Runs on YouTube pages. Lets the side panel seek the video and read its position.
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  const video = document.querySelector("video.html5-main-video") || document.querySelector("video");
  if (msg?.type === "seek") {
    if (!video) return reply({ ok: false });
    video.currentTime = msg.secs;
    video.play().catch(() => {});
    return reply({ ok: true });
  }
  if (msg?.type === "time") {
    return reply({ ok: !!video, secs: video ? video.currentTime : 0, paused: video ? video.paused : true });
  }
});
