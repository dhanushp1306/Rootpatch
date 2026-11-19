# AutoPatch -- Complete Project Development Plan

**Hackathon duration:** 24 hours\
**Domain:** Software Engineering & Automation\
**Challenge area:** Intelligent Debugging & Program Repair\
**Expected outcome:** Tested, explainable code patches

## 1. Project Overview

AutoPatch is an AI-assisted software debugging and repair platform. It
accepts a source file or code project, analyzes its structure, detects
potential bugs, explains likely root causes, generates focused repair
patches, validates those patches through testing, and lets developers
approve or reject every change.

**Core workflow:**

1.  Upload a ZIP project or individual source files.
2.  Analyze project structure, languages, dependencies, entry points,
    and tests.
3.  Detect syntax, runtime, logical, suspicious, and security-related
    issues.
4.  Explain each issue's likely root cause and triggering conditions.
5.  Generate a focused patch.
6.  Run existing tests and targeted tests against the proposed patch.
7.  Show a before-and-after code comparison and validation evidence.
8.  Let the developer accept, reject, or revert changes.
9.  Record bugs, patches, decisions, and test results in change history.

### Recommended scope

For a 24-hour hackathon, support **Python projects first**. Build a
complete workflow for one language rather than superficial support for
many languages. Clearly label findings as confirmed, likely, or
informational. Do not claim a patch is verified unless tests were
actually executed.

## 2. Technology Stack

  -----------------------------------------------------------------------
  Layer                   Recommended technology  Purpose
  ----------------------- ----------------------- -----------------------
  Frontend                React + Vite +          Dashboard and code
                          TypeScript              review

  Styling                 Tailwind CSS            User interface

  Backend                 Python + FastAPI        API and application
                                                  logic

  Code structure analysis Python AST              Parse Python source

  Static analysis         Ruff, Pylint            Code quality and likely
                                                  defects

  Security scanning       Bandit                  Detect selected Python
                                                  security risks

  AI reasoning            LLM API                 Root-cause analysis and
                                                  patch proposals

  Patch format            Unified diff            Reviewable code changes

  Testing                 Pytest                  Execute tests and
                                                  validate fixes

  Code comparison         Git / difflib           Before-and-after
                                                  comparison

  Database                SQLite                  Store projects, scans,
                                                  bugs, patches, and
                                                  history

  Execution isolation     Docker                  Run uploaded code in a
                                                  restricted environment

  API communication       REST                    Frontend/backend
                                                  integration
  -----------------------------------------------------------------------

Use static-analysis tools and tests as independent evidence. The LLM
should assist with reasoning and patch proposals, not be the sole
authority for declaring a bug or fix correct.

## 3. Functional Modules

### Module 1: Project Upload and Code Analysis

**Features** - Upload ZIP archives and individual source files. -
Validate file types and enforce upload limits. - Safely extract project
archives. - Inspect folders and files. - Identify supported programming
languages. - Identify entry points and important source files. - Read
dependency manifests such as `requirements.txt` and `pyproject.toml`. -
Discover existing test files and test configuration. - Generate a
project overview.

**Example analysis report** - Project name: Marks Calculator - Language:
Python - Source files: 12 - Test files: 3 - Dependencies: 8

These values are illustrative; the application must display actual scan
results.

### Module 2: Intelligent Bug Detection

Detect and classify:

  -----------------------------------------------------------------------
  Category                Examples                Possible detection
                                                  approach
  ----------------------- ----------------------- -----------------------
  Syntax                  Invalid syntax,         Python compiler / AST
                          malformed statements    parsing

  Runtime                 Division by zero,       Static analysis and
                          undefined names, index  controlled execution
                          errors                  

  Logical                 Incorrect conditions,   AI-assisted review and
                          boundary errors, wrong  targeted tests
                          calculations            

  Security                Hardcoded secrets,      Bandit and dedicated
                          unsafe functions,       pattern checks
                          injection risks         

  Suspicious code         Unusual or potentially  Static rules and AI
                          unsafe constructs       review

  Performance             Inefficient loops or    Selected rules and
                          repeated work           AI-assisted review
  -----------------------------------------------------------------------

Additional requirements: - Associate each finding with a file and line
number where possible. - Avoid duplicate findings. - Include evidence
and detection method. - Distinguish confirmed defects from possible
issues. - Do not claim comprehensive detection of all bugs.

### Module 3: Root-Cause Analysis

For each finding, provide: 1. What went wrong? 2. Where did it occur? 3.
Why might it happen? 4. What input or condition triggers it? 5. What is
the potential impact? 6. Which other functions or files may be affected?
7. What repair is recommended?

**Example**

-   Bug: Division by zero
-   Location: `calculator.py`, line 8
-   Root cause: The function divides by the number of students without
    checking whether the input list is empty.
-   Trigger: An empty list is supplied.
-   Impact: A `ZeroDivisionError` interrupts execution.
-   Suggested fix: Validate the input before division.

### Module 4: Automatic Patch Generation

**Features** - Generate a repair proposal using an LLM. - Request
minimal, targeted changes. - Preserve unrelated code. - Produce a
unified diff. - Display original and proposed code. - Explain why the
patch should address the issue. - Store the proposed patch separately
from the original project. - Apply the patch only to a temporary working
copy before approval.

The system must not silently overwrite the uploaded original project.
Validate patch paths and ensure patches cannot write outside the project
workspace.

### Module 5: Testing and Validation

This is a critical module.

**Features** - Discover and run existing tests. - Generate targeted
tests for the reported issue. - Test normal inputs. - Test boundary
values. - Test invalid inputs. - Run regression tests after patching. -
Compare baseline and patched test results. - Capture test output, exit
status, and execution time.

**Example report (illustrative only)**

  Test state       Passed   Failed
  -------------- -------- --------
  Before patch          7        3
  After patch          10        0

Use explicit validation statuses: - Patch generated - Applied to
temporary copy - Tests passed - Tests failed - Regression detected -
Validation incomplete

A patch must not be marked verified merely because the AI model says it
is correct. A passing test suite is evidence, not proof that every
possible defect has been eliminated.

### Module 6: Explanation and Developer Review

The review screen should show: - Bug description and category. - File
name and line number. - Root-cause explanation. - Triggering input or
condition. - Original code. - Proposed code. - Highlighted unified
diff. - Patch explanation. - Test results. - Severity and confidence. -
Accept and reject controls.

The developer must understand and approve a change before it is applied
to the original project.

### Module 7: Bug Prioritization

Rank findings using: - Severity. - Potential impact. - Confidence. -
Reproducibility.

Suggested levels:

  Priority   Meaning
  ---------- -----------------------------------------------
  Critical   Severe security or application-breaking issue
  High       Major functional failure
  Medium     Limited functional or edge-case issue
  Low        Minor quality or performance concern

Keep severity and confidence separate. A potentially critical issue with
low confidence should be flagged for investigation rather than silently
dismissed.

### Module 8: Safe Change History

Record: - Project ID and scan ID. - Bug ID. - Original code or patch
base reference. - Proposed patch. - Patch status. - Test results. -
Developer decision. - Timestamp. - Revert information.

Suggested statuses: - Pending review - Accepted - Rejected - Validated -
Reverted

Support reverting an accepted patch where feasible. Preserve enough
information to reconstruct what changed and why.

## 4. Frontend Pages

Build six primary pages:

1.  **Dashboard**
    -   Project count, scan count, bug summary, severity breakdown,
        recent activity.
2.  **Project Upload and Analysis**
    -   ZIP/file upload, project tree, language, dependencies, test
        discovery.
3.  **Bug Explorer**
    -   Search, filter, severity, confidence, category, file and line
        details.
4.  **Patch Review**
    -   Root cause, original code, proposed code, unified diff,
        accept/reject actions.
5.  **Test Results**
    -   Test cases, pass/fail status, logs, before-and-after comparison,
        regression status.
6.  **Change History**
    -   Scan history, patch attempts, accepted/rejected changes,
        validation and revert records.

Keep the interface focused on developer workflows rather than making it
a generic chatbot.

## 5. Backend Architecture

Suggested project structure:

``` text
autopatch/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── projects.py
│   │   │   ├── scans.py
│   │   │   ├── bugs.py
│   │   │   ├── patches.py
│   │   │   ├── tests.py
│   │   │   └── history.py
│   │   ├── services/
│   │   │   ├── project_analyzer.py
│   │   │   ├── bug_detector.py
│   │   │   ├── root_cause.py
│   │   │   ├── patch_generator.py
│   │   │   ├── patch_applier.py
│   │   │   ├── test_runner.py
│   │   │   └── prioritizer.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── database/
│   │   └── utils/
│   ├── workspace/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/
│   │   └── types/
│   └── package.json
├── docker/
├── docs/
├── README.md
└── docker-compose.yml
```

Keep API routes, business logic, database models, and request/response
schemas separate. Agree on API contracts early so frontend and backend
work can proceed in parallel.

## 6. Database Design

Use SQLite for the hackathon prototype.

  -----------------------------------------------------------------------
  Table                               Purpose
  ----------------------------------- -----------------------------------
  `projects`                          Uploaded project metadata

  `scans`                             Scan execution records and status

  `bugs`                              Findings, evidence, location,
                                      severity, confidence

  `patches`                           Proposed code changes and patch
                                      status

  `test_results`                      Test runs, output, pass/fail counts

  `change_history`                    Developer decisions, timestamps,
                                      and revert records
  -----------------------------------------------------------------------

Relationships: - One project can have multiple scans. - One scan can
identify multiple bugs. - One bug can have multiple patch attempts. -
One patch can have multiple test runs. - Each patch has a recorded
review decision.

## 7. 24-Hour Development Schedule

This plan assumes a small team working in parallel.

  -----------------------------------------------------------------------
  Time                    Work                    Expected output
  ----------------------- ----------------------- -----------------------
  Hour 0--2               Planning, repository    Running skeleton and
                          setup, architecture,    agreed interfaces
                          API contracts           

  Hour 2--6               Upload, safe            Project analysis and
                          extraction, project     initial findings
                          inspection,             
                          dependency/test         
                          discovery,              
                          static-analysis         
                          integration             

  Hour 6--10              Bug classification, AI  Structured bug reports
                          analysis, root-cause    
                          reports                 

  Hour 10--14             Patch generation,       Reviewable patch
                          unified diffs,          workflow
                          temporary patch         
                          application, review     
                          controls                

  Hour 14--18             Existing tests,         Validation evidence
                          generated tests,        
                          regression checks,      
                          result capture          

  Hour 18--21             Dashboard, bug          End-to-end interface
                          explorer, patch review, 
                          results and history     
                          integration             

  Hour 21--23             Integration tests,      Stable demo candidate
                          security checks, error  
                          handling, bug fixes     

  Hour 23--24             README, screenshots,    Submission-ready
                          demo project,           prototype
                          presentation and        
                          submission              
  -----------------------------------------------------------------------

**Scheduling rule:** Do not postpone integration until the final hours.
Define API contracts in the first two hours and integrate continuously.
Keep a working end-to-end path before adding optional features.

## 8. Team Responsibilities

For a four-person team:

  -----------------------------------------------------------------------
  Team member                         Primary responsibility
  ----------------------------------- -----------------------------------
  Developer 1                         Backend architecture, upload,
                                      project analysis, database

  Developer 2                         AI integration, bug reasoning,
                                      root-cause analysis, patch
                                      generation

  Developer 3                         React frontend, dashboard, bug
                                      explorer, patch review

  Developer 4                         Test execution, validation,
                                      history, integration and security
  -----------------------------------------------------------------------

All members should help with integration and final debugging. For a
three-person team, combine project analysis with backend work and share
testing/integration responsibilities.

## 9. Security and Reliability Requirements

Uploaded projects are untrusted input. Never execute arbitrary uploaded
code directly on the application host.

Implement: - File-type, archive-size, file-count, and extracted-size
limits. - Safe ZIP extraction that blocks path traversal and symlink
escapes. - Exclusion of `.env`, credentials, private keys, and
unnecessary sensitive files from AI prompts. - Temporary workspaces for
patch generation and testing. - Docker isolation with non-root
execution, CPU/memory limits, and timeouts. - Network disabled during
test execution unless explicitly required. - Restricted filesystem
access and no privileged container mode. - Preservation of the original
uploaded project. - Explicit developer approval before applying changes
to the original. - Clear handling of timeouts, malformed AI responses,
failed patches, and failed tests.

If secure container execution cannot be completed during the hackathon,
restrict execution to trusted sample projects and clearly disclose the
limitation.

## 10. Final Acceptance Checklist

### Project analysis

-   [ ] Upload ZIP and individual source files.
-   [ ] Extract and inspect project structure.
-   [ ] Identify dependencies and test files.

### Bug detection

-   [ ] Detect syntax and runtime problems.
-   [ ] Identify potential logical bugs.
-   [ ] Identify suspicious and security-related code.
-   [ ] Assign severity and confidence.

### Root-cause analysis

-   [ ] Explain the reason behind each issue.
-   [ ] Identify affected file and code section.
-   [ ] Identify triggering inputs or conditions.

### Patch generation

-   [ ] Generate focused repair suggestions.
-   [ ] Display before-and-after code.
-   [ ] Explain proposed modifications.
-   [ ] Allow patch acceptance and rejection.

### Testing and validation

-   [ ] Run existing project tests.
-   [ ] Generate targeted test cases.
-   [ ] Run regression tests.
-   [ ] Display actual test results.

### History and presentation

-   [ ] Record bug and patch history.
-   [ ] Track accepted and rejected changes.
-   [ ] Support patch reversion.
-   [ ] Present results through an understandable dashboard.

## 11. Final Deliverables

The submitted prototype should demonstrate:

1.  Working project upload.
2.  Project structure and dependency analysis.
3.  Multiple types of bug detection.
4.  AI-assisted root-cause explanations.
5.  Automatic patch suggestions.
6.  Side-by-side code comparisons.
7.  Developer approval and rejection.
8.  Automated test execution.
9.  Before-and-after validation.
10. Bug prioritization.
11. Patch and change history.
12. Safe handling of uploaded projects.

## 12. Demonstration Strategy

Prepare a small Python project containing several deliberately
introduced and reproducible defects, such as: - Division by zero for
empty input. - Incorrect boundary condition. - Incorrect calculation or
return value. - A security issue detectable by a static-analysis rule.

During the demonstration:

1.  Upload the sample project.
2.  Show the detected project structure.
3.  Run a scan and inspect findings.
4.  Open a bug and explain its root cause.
5.  Generate a focused patch.
6.  Review the before-and-after diff.
7.  Apply the patch to the temporary copy.
8.  Run existing and targeted tests.
9.  Show actual validation results.
10. Accept or reject the patch.
11. Open change history and demonstrate traceability.

Use actual test output in the demo. Do not fabricate success metrics or
imply that a sample result came from a live run if it did not.

## 13. Scope Priorities

### Must have

-   Python project upload and inspection.
-   Static bug detection.
-   AI-assisted root-cause explanation.
-   Focused patch generation.
-   Unified diff review.
-   Developer accept/reject workflow.
-   Actual test execution.
-   Basic regression validation.
-   Bug and patch history.

### Should have if time permits

-   AI-generated edge-case tests.
-   Security scanning.
-   Severity and confidence filters.
-   Patch reversion.
-   More detailed project dependency analysis.

### Avoid in the 24-hour build

-   Universal support for many programming languages.
-   Fully autonomous modification without approval.
-   Claims of detecting every logical bug.
-   Complex distributed execution infrastructure.
-   Unrestricted execution of uploaded projects.
-   Features that cannot be tested or demonstrated.

## 14. Definition of Success

AutoPatch succeeds as a hackathon prototype when a developer can upload
a supported project, inspect meaningful findings, understand at least
one reproducible bug, review a focused repair, run tests against the
proposed change, see truthful validation evidence, and explicitly accept
or reject the patch.

**Final recommendation:** Prioritize a complete, evidence-driven Python
debugging and repair workflow. A smaller system with reliable detection,
explainable patches, safe execution, and real test results is stronger
than a broad system that only demonstrates an attractive interface or
AI-generated code.
