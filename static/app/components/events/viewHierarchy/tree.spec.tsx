import {render, screen, userEvent} from 'sentry-test/reactTestingLibrary';

import {ViewHierarchyTree} from './tree';

const DEFAULT_VALUES = {alpha: 1, height: 1, width: 1, x: 1, y: 1, visible: true};
const MOCK_DATA = {
  ...DEFAULT_VALUES,
  id: 'parent',
  type: 'Container',
  children: [
    {
      ...DEFAULT_VALUES,
      id: 'intermediate',
      type: 'Nested Container',
      children: [
        {
          ...DEFAULT_VALUES,
          id: 'leaf',
          type: 'Text',
          children: [],
        },
      ],
    },
  ],
};

describe('View Hierarchy Tree', function () {
  it('renders nested JSON', function () {
    render(<ViewHierarchyTree hierarchy={MOCK_DATA} />);

    expect(screen.getByText('Container')).toBeInTheDocument();
    expect(screen.getByText('Nested Container')).toBeInTheDocument();
    expect(screen.getByText('Text')).toBeInTheDocument();
  });

  it('can collapse and expand sections with children', function () {
    render(<ViewHierarchyTree hierarchy={MOCK_DATA} />);

    userEvent.click(screen.getAllByLabelText('Collapse')[1]);
    expect(screen.queryByText('Text')).not.toBeInTheDocument();
    userEvent.click(screen.getByLabelText('Expand'));
    expect(screen.getByText('Text')).toBeInTheDocument();
  });
});
