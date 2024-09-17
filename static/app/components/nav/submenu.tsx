import {Fragment} from 'react';
import styled from '@emotion/styled';
import {motion} from 'framer-motion';

import Feature from 'sentry/components/acl/feature';
import Link from 'sentry/components/links/link';
import {useIndicator} from 'sentry/components/nav/useIndicator';
import type {SubmenuItem} from 'sentry/components/nav/utils';
import {
  getActiveProps,
  getActiveStatus,
  useLocationDescriptor,
} from 'sentry/components/nav/utils';
import {space} from 'sentry/styles/space';
import theme from 'sentry/utils/theme';
import {useLocation} from 'sentry/utils/useLocation';

const Submenu = styled(motion.div)`
  position: relative;
  border-right: 1px solid ${theme.translucentGray200};
  background: ${theme.surface300};
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  flex-direction: column;
  width: 150px;
  z-index: ${theme.zIndex.sidebarPanel};
`;

function Items({children}) {
  const {indicatorProps, containerProps} = useIndicator();

  return (
    <Fragment>
      <Indicator {...indicatorProps} />
      <ItemList {...containerProps}>{children}</ItemList>
    </Fragment>
  );
}

const ItemList = styled('ul')`
  list-style: none;
  margin: 0;
  padding: 0;
  padding-top: ${space(1)};
  display: flex;
  flex-direction: column;
  width: 100%;
  color: ${theme.gray400};
`;

function Item({to, label, check, ...props}: React.PropsWithChildren<SubmenuItem>) {
  const location = useLocation();
  const activeProps = getActiveProps(getActiveStatus({to, label}, location));
  const toProps = useLocationDescriptor(to);

  const FeatureGuard = check ? Feature : Fragment;
  const featureGuardProps: any = check
    ? {
        features: check.features,
        hookName: check.hook ? (`feature-disabled:${check.hook}` as const) : undefined,
      }
    : {};

  return (
    <FeatureGuard {...featureGuardProps}>
      <ItemWrapper>
        <Link to={toProps} {...activeProps} {...props}>
          {label}
        </Link>
      </ItemWrapper>
    </FeatureGuard>
  );
}

const ItemWrapper = styled('li')`
  a {
    display: flex;
    padding: 5px ${space(1.5)};
    height: 32px;
    align-items: center;
    color: inherit;
    font-size: ${theme.fontSizeMedium};
    font-weight: ${theme.fontWeightNormal};
    line-height: 177.75%;
    margin-inline: ${space(1)};
    border: 1px solid transparent;
    border-radius: ${theme.borderRadius};

    &:hover {
      color: ${theme.gray500};
      /* background: rgba(62, 52, 70, 0.09); */
    }

    &.active {
      color: ${theme.gray500};
      background: rgba(62, 52, 70, 0.09);
      border: 1px solid ${theme.translucentGray100};
    }
  }
`;

const Indicator = styled(motion.span)`
  position: absolute;
  left: 0;
  right: 0;
  opacity: 0;
  pointer-events: none;
  margin-inline: ${space(1)};
  height: 32px;
  background: rgba(62, 52, 70, 0.09);
  border-radius: ${theme.borderRadius};
`;

const FooterWrapper = styled('div')`
  position: relative;
  border-top: 1px solid ${theme.translucentGray200};
  background: ${theme.surface300};
  display: flex;
  flex-direction: row;
  align-items: stretch;
  padding-block: ${space(1)};
`;

function Body({children}) {
  return <Items>{children}</Items>;
}

function Footer({children}) {
  return (
    <FooterWrapper>
      <Items>{children}</Items>
    </FooterWrapper>
  );
}

export default Object.assign(Submenu, {Body, Footer, Item});
