/**
 * Cron-driven trigger for the PM internship watcher.
 *
 * GitHub Actions' `schedule:` is best-effort and gets heavily deprioritised --
 * measured at ~1 run delivered per 8 requested, with gaps up to 7 hours.
 * `workflow_dispatch` is not throttled, so this Worker supplies a reliable
 * clock and asks GitHub to run the scan on each tick.
 *
 * Requires a secret GITHUB_TOKEN: a fine-grained PAT scoped to the watcher
 * repo with Actions: Read and write.
 */

const API = "https://api.github.com/repos/{repo}/actions/workflows/{file}/dispatches";

export default {
  async scheduled(event, env, ctx) {
    if (!env.GITHUB_TOKEN) {
      console.error("GITHUB_TOKEN is not set; run: wrangler secret put GITHUB_TOKEN");
      return;
    }

    const url = API
      .replace("{repo}", env.GITHUB_REPO)
      .replace("{file}", env.WORKFLOW_FILE);

    const response = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pm-internship-trigger",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: env.GIT_REF || "main" }),
    });

    // 204 No Content is the success case for workflow dispatch.
    if (response.status === 204) {
      console.log(`dispatched (cron: ${event.cron})`);
      return;
    }

    const detail = (await response.text()).slice(0, 300);
    console.error(`dispatch failed ${response.status}: ${detail}`);
    // Throwing marks the invocation as errored so it shows up in observability.
    throw new Error(`GitHub dispatch failed with ${response.status}`);
  },
};
