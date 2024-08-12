import styled from '@emotion/styled';

import Link from 'sentry/components/links/link';
import {Tooltip} from 'sentry/components/tooltip';
import {IconPlay} from 'sentry/icons';
import {t, tn} from 'sentry/locale';
import {space} from 'sentry/styles/space';
import type {Group} from 'sentry/types/group';
import {decodeScalar} from 'sentry/utils/queryString';
import useReplayCountForIssues from 'sentry/utils/replayCount/useReplayCountForIssues';
import normalizeUrl from 'sentry/utils/url/normalizeUrl';
import {useLocation} from 'sentry/utils/useLocation';
import useOrganization from 'sentry/utils/useOrganization';

interface Props {
  group: Group;
}

/**
 * Show the count of how many replays are associated to an issue.
 */
function IssueReplayCount({group}: Props) {
  const organization = useOrganization();
  const location = useLocation();
  const {getReplayCountForIssue} = useReplayCountForIssues({
    statsPeriod: decodeScalar(location.query.statsPeriod) ?? '90d',
  });
  const count = getReplayCountForIssue(group.id, group.issueCategory);

  if (count === undefined || count === 0) {
    return null;
  }

  const countDisplay = count > 50 ? '50+' : count;
  const titleOver50 = t('This issue has 50+ replays available to view');
  const title50OrLess = tn(
    'This issue has %s replay available to view',
    'This issue has %s replays available to view',
    count
  );

  return (
    <Tooltip title={count > 50 ? titleOver50 : title50OrLess}>
      <ReplayCountLink
        to={normalizeUrl(
          `/organizations/${organization.slug}/issues/${group.id}/replays/`
        )}
        aria-label={t('replay-count')}
      >
        <IconPlay size="xs" />
        {countDisplay}
      </ReplayCountLink>
    </Tooltip>
  );
}

const ReplayCountLink = styled(Link)`
  display: inline-flex;
  color: ${p => p.theme.gray400};
  font-size: ${p => p.theme.fontSizeSmall};
  gap: 0 ${space(0.5)};
`;

export default IssueReplayCount;
