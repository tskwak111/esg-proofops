import { ClaimDetailView } from "./ClaimDetail";
import { ClaimList } from "./ClaimList";
import type { ClaimWorkspaceProps } from "./claimTypes";

// Keep the original entry points for routes and existing component consumers.
export type { ClaimWorkspaceProps } from "./claimTypes";
export { PartialClaimSummary, ReviewedContextSection } from "./ClaimDetail";
export { ReviewQueueWorkspace } from "./ReviewQueue";

export function ClaimWorkspace(props: ClaimWorkspaceProps) {
  return props.claimId ? <ClaimDetailView {...props} claimId={props.claimId} /> : <ClaimList {...props} />;
}
