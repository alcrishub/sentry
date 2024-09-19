import {Fragment} from 'react';
import styled from '@emotion/styled';

import {CodeSnippet} from 'sentry/components/codeSnippet';
import LoadingIndicator from 'sentry/components/loadingIndicator';
import {space} from 'sentry/styles/space';
import {SQLishFormatter} from 'sentry/utils/sqlish/SQLishFormatter';
import {useFullSpanFromTrace} from 'sentry/views/insights/common/queries/useFullSpanFromTrace';
import {prettyPrintJsonString} from 'sentry/views/insights/database/utils/jsonUtils';
import {ModuleName} from 'sentry/views/insights/types';
import Alert from 'sentry/components/alert';
import {t} from 'sentry/locale';
import ClippedBox, {ClipFade} from 'sentry/components/clippedBox';
import {IconOpen} from 'sentry/icons';

const formatter = new SQLishFormatter();

const INDEXED_SPAN_SORT = {
  field: 'span.self_time',
  kind: 'desc' as const,
};

interface Props {
  moduleName: ModuleName;
  filters?: Record<string, string>;
  group?: string;
  shortDescription?: string;
}

export function FullSpanDescription({
  group,
  shortDescription,
  filters,
  moduleName,
}: Props) {
  const {
    data: fullSpan,
    isLoading,
    isFetching,
  } = useFullSpanFromTrace(group, [INDEXED_SPAN_SORT], Boolean(group), filters);

  const description = fullSpan?.description ?? shortDescription;
  const system = fullSpan?.data?.['db.system'];

  if (isLoading && isFetching) {
    return (
      <PaddedSpinner>
        <LoadingIndicator mini hideMessage relative />
      </PaddedSpinner>
    );
  }

  if (!description) {
    return null;
  }

  if (moduleName === ModuleName.DB) {
    if (system === 'mongodb') {
      let stringifiedQuery = '';
      let shouldDisplayTruncatedWarning = false;
      let result: ReturnType<typeof prettyPrintJsonString> | undefined = undefined;

      if (fullSpan?.sentry_tags) {
        result = prettyPrintJsonString(fullSpan?.sentry_tags?.description);
      } else if (description) {
        result = prettyPrintJsonString(description);
      } else if (fullSpan?.sentry_tags?.description) {
        result = prettyPrintJsonString(fullSpan?.sentry_tags?.description);
      } else {
        stringifiedQuery = description || fullSpan?.sentry_tags?.description || 'N/A';
        shouldDisplayTruncatedWarning = false;
      }

      if (result) {
        const {prettifiedQuery, isTruncated} = result;
        stringifiedQuery = prettifiedQuery;
        shouldDisplayTruncatedWarning = isTruncated;
      }

      if (shouldDisplayTruncatedWarning) {
        return (
          <StyledClippedBox
            onReveal={console.log}
            btnText={t('View full query')}
            buttonProps={{icon: <IconOpen />}}
          >
            <CodeSnippet language="json">{stringifiedQuery}</CodeSnippet>
          </StyledClippedBox>
        );
      }

      return <CodeSnippet language="json">{stringifiedQuery}</CodeSnippet>;
    }

    return (
      <CodeSnippet language="sql">
        {formatter.toString(description, {maxLineLength: LINE_LENGTH})}
      </CodeSnippet>
    );
  }

  if (moduleName === ModuleName.RESOURCE) {
    return <CodeSnippet language="http">{description}</CodeSnippet>;
  }

  return <Fragment>{description}</Fragment>;
}

const LINE_LENGTH = 60;

const PaddedSpinner = styled('div')`
  padding: 0 ${space(0.5)};
`;

const StyledClippedBox = styled(ClippedBox)`
  > div > div {
    z-index: 1;
  }
`;
