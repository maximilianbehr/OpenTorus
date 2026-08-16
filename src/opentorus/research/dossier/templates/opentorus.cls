%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% OpenTorus dossier report class.                                              %
%                                                                              %
% Self-contained: everything the generated report needs (page geometry, title  %
% block, running heads, the OpenTorus macros) lives here. It replaces the       %
% third-party preprint.cls that used to be vendored alongside it.              %
%                                                                              %
% Two things this buys beyond styling:                                         %
%   * no `lineno' — that package pinned the stock `verbatim' such that          %
%     fvextra's breaklines silently never fired and long output ran off the     %
%     page;                                                                     %
%   * no unused machinery (two-column mode, abstract/keywords/MSC/novelty       %
%     front matter, cleveref equation formats) that the generator never emits.  %
%                                                                              %
% Every optional package is probed with \IfFileExists before use, so a minimal  %
% TeX installation still compiles a report; it just gets a plainer one.         %
%                                                                              %
% The palette below is mirrored in opentorus/research/dossier/theme.py, which   %
% styles the HTML report. A test pins the two to the same values — change both  %
% or neither.                                                                   %
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{opentorus}[2026/08/16 OpenTorus dossier report class]

\DeclareOption*{\PassOptionsToClass{\CurrentOption}{scrartcl}}
\ProcessOptions\relax
\LoadClass[11pt, oneside]{scrartcl}

\RequirePackage{xcolor}
\RequirePackage{etoolbox}

%% ------------------------------------------------------- feature detection ---
% Probed once into booleans. A bare "#" inside an \IfFileExists branch is read
% as a macro parameter ("Illegal parameter number in \reserved@a"), so the
% branches below must stay parameter-free.
\newif\ifot@fonts     \ot@fontsfalse
\newif\ifot@tcb       \ot@tcbfalse
\newif\ifot@fvextra   \ot@fvextrafalse
\newif\ifot@enumitem  \ot@enumitemfalse
\newif\ifot@microtype \ot@microtypefalse

\IfFileExists{libertinus.sty}{\IfFileExists{libertinust1math.sty}{\ot@fontstrue}{}}{}
\IfFileExists{tcolorbox.sty}{\ot@tcbtrue}{}
\IfFileExists{fvextra.sty}{\ot@fvextratrue}{}
\IfFileExists{enumitem.sty}{\ot@enumitemtrue}{}
\IfFileExists{microtype.sty}{\ot@microtypetrue}{}

%% ---------------------------------------------------------------- palette ---
\definecolor{otaccent}{HTML}{1B4965}   % headings, links, artifact ids
\definecolor{otaccentlt}{HTML}{7FA3BC} % rules on output blocks
\definecolor{otmuted}{HTML}{5A6672}    % secondary labels
\definecolor{otrule}{HTML}{D3DAE1}     % hairlines
\definecolor{otsurface}{HTML}{F4F6F8}  % panel / output background
\definecolor{otwarn}{HTML}{9A5B0A}     % caveats, gap markers, "open"
\definecolor{otwarnbg}{HTML}{FCF6EA}
\definecolor{otok}{HTML}{176B3A}       % supported / verified / succeeded
\definecolor{otbad}{HTML}{9B2226}      % refuted / failed / invalid

%% ------------------------------------------------------------------ fonts ---
% libertinust1math already supplies the AMS symbol set, so amssymb must NOT be
% loaded next to it (clashing \Bbbk and friends).
\RequirePackage{amsmath}
\ifot@fonts
  \RequirePackage[ScaleTT=.95]{libertinus}
  \RequirePackage{libertinust1math}
\else
  \RequirePackage{amssymb}
\fi
\RequirePackage{amsthm}
\ifot@microtype\RequirePackage{microtype}\fi

%% ----------------------------------------------------------------- layout ---
\RequirePackage{geometry}
\geometry{left = 3.0cm, right = 3.0cm, top = 3.0cm, bottom = 3.0cm}
\RequirePackage{graphicx}
\RequirePackage{url}          % \path{} for file paths
\RequirePackage{scrdate}      % \ISOToday for the footer

%% ------------------------------------------------------------ title block ---
\date{}
\RequirePackage[noblocks]{authblk}
\renewcommand\Affilfont{\itshape\small}
\newlength{\authorsep}
\setlength\authorsep{2\baselineskip}
\renewcommand\Authsep{\hspace*{\authorsep}}
\renewcommand\Authand{\hspace*{\authorsep}}
\renewcommand\Authands{\hspace*{\authorsep}}
\newcommand{\email}[1]{{\normalfont Email:~\texttt{\href{mailto:#1}{#1}}}}
\newcommand{\orcid}[1]{{\normalfont ORCID:~\texttt{\href{https://orcid.org/#1}{#1}}}}

%% ----------------------------------------------------- running head / foot ---
\RequirePackage{scrlayer-scrpage}
\let\@shorttitle\empty
\newcommand{\shorttitle}[1]{\gdef\@shorttitle{#1}}
\let\@shortauthor\empty
\newcommand{\shortauthor}[1]{\gdef\@shortauthor{#1}}
\let\@shortinstitute\empty
\newcommand{\shortinstitute}[1]{\gdef\@shortinstitute{#1}}
\let\@shortdate\empty
\newcommand{\shortdate}[1]{\gdef\@shortdate{#1}}
\ohead{\usekomafont{pagenumber}\thepage}

\let\ot@oldmaketitle\maketitle
\renewcommand{\maketitle}{%
  \hypersetup{%
    pdftitle    = {\@title},
    pdfauthor   = {\@shortauthor},
    pdfsubject  = {\@shorttitle},
    pdfcreator  = {OpenTorus},
  }
  \ifx\@shortauthor\empty
    \ifx\@shorttitle\empty\else\ihead{\@shorttitle}\fi
  \else
    \ifx\@shorttitle\empty
      \ihead{\@shortauthor}
    \else
      \ihead{\@shortauthor:~\@shorttitle}
    \fi
  \fi
  \renewcommand*\pagemark{}
  \ifx\@shortinstitute\empty
    \ifoot*{\small Preprint.}
  \else
    \ifoot*{\small Preprint (\@shortinstitute).}
  \fi
  \ifx\@shortdate\empty
    \ofoot*{\small \ISOToday}
  \else
    \ofoot*{\small \@shortdate}
  \fi
  \KOMAoptions{headsepline = true, footsepline = true, plainfootsepline = true}
  \ModifyLayer[addvoffset=-.6ex]{scrheadings.foot.above.line}
  \ModifyLayer[addvoffset=-.6ex]{plain.scrheadings.foot.above.line}
  \ot@oldmaketitle
}

%% --------------------------------------------------------------- headings ---
\addtokomafont{title}{\color{otaccent}}
\setkomafont{section}{\normalfont\sffamily\Large\bfseries\color{otaccent}}
\setkomafont{subsection}{\normalfont\sffamily\large\bfseries\color{otaccent}}
\setkomafont{subsubsection}{\normalfont\sffamily\normalsize\bfseries\color{otaccent}}
\setkomafont{paragraph}{\normalfont\sffamily\normalsize\bfseries\color{otaccent!85!black}}

% A thin hairline under every \section heading.
\renewcommand*{\sectionlinesformat}[4]{%
  \ifstrequal{#1}{section}{%
    \parbox{\dimexpr\linewidth-#2\relax}{%
      \raggedsection\@hangfrom{#3}{#4}\par
      \vspace{.30\baselineskip}%
      {\color{otrule}\hrule height .7pt}%
    }%
  }{\@hangfrom{\hskip #2#3}{#4}}%
}

\setcounter{secnumdepth}{3}
\setcounter{tocdepth}{2}

%% ------------------------------------------------------------------ lists ---
\ifot@enumitem
  \RequirePackage{enumitem}
  \setlist{itemsep=.2\baselineskip, parsep=0pt, topsep=.35\baselineskip}
\fi

%% ----------------------------------------------------------------- tables ---
\RequirePackage{booktabs}
\RequirePackage{tabularx}
\RequirePackage{array}
\renewcommand{\arraystretch}{1.22}
% 4pt rather than the default 6pt: artifact ids and status chips are unbreakable
% boxes, so every point of inter-column padding is a point the statement column
% does not get.
\setlength{\tabcolsep}{4pt}
% Ragged, wrapping columns. Justified narrow columns produce rivers and overfull
% boxes once a cell holds something like COUNTEREXAMPLE_CANDIDATE.
%
% The leading \strut matters: a p-column aligns on its first baseline, so a cell
% whose first line is short (a \small artifact id, a status chip) would otherwise
% hang below the neighbouring statement it belongs to.
\newcolumntype{L}{>{\strut\raggedright\arraybackslash}X}
\newcolumntype{P}[1]{>{\strut\raggedright\arraybackslash}p{#1}}
% Column heading.
\newcommand{\othead}[1]{\textcolor{otaccent}{\footnotesize\bfseries #1}}
% Secondary label in a table cell (a claim type under its id, etc.).
\newcommand{\ottype}[1]{{\scriptsize\sffamily\color{otmuted}#1}}

%% ------------------------------------------------------- verbatim / output ---
% Captured program output is the ugliest part of a generated report: long lines
% used to run straight off the right edge of the page. `otoutput' breaks them
% and sets the block on a tinted panel.
\RequirePackage{fancyvrb}
\ifot@fvextra
  \RequirePackage{fvextra}
  \DefineVerbatimEnvironment{otoutput}{Verbatim}{%
    fontsize=\small, breaklines=true, breakanywhere=true,
    breaksymbolleft=\textcolor{otaccentlt}{\tiny\ensuremath{\hookrightarrow}},
    xleftmargin=0pt, samepage=false}
  % Anything that still says \begin{verbatim} gets the same treatment. This only
  % works because this class does not load lineno.
  \RecustomVerbatimEnvironment{verbatim}{Verbatim}{%
    fontsize=\small, breaklines=true, breakanywhere=true,
    breaksymbolleft=\textcolor{otaccentlt}{\tiny\ensuremath{\hookrightarrow}},
    xleftmargin=0pt, samepage=false}
\else
  \DefineVerbatimEnvironment{otoutput}{Verbatim}{%
    fontsize=\small, xleftmargin=0pt, samepage=false}
  \RecustomVerbatimEnvironment{verbatim}{Verbatim}{%
    fontsize=\small, xleftmargin=0pt, samepage=false}
\fi

\ifot@tcb
  \RequirePackage{tcolorbox}
  \tcbuselibrary{skins,breakable}
  \newenvironment{ot@outputbox}{%
    \begin{tcolorbox}[enhanced, breakable, sharp corners,
      colback=otsurface, colframe=otsurface, boxrule=0pt,
      borderline west={2pt}{0pt}{otaccentlt},
      left=7pt, right=7pt, top=5pt, bottom=5pt,
      before skip=.7\baselineskip, after skip=.7\baselineskip]%
  }{\end{tcolorbox}}
  % Wrapped in place rather than with \tcolorboxenvironment: capturing the body
  % as an argument typesets it at its natural width, which defeats breaklines.
  \BeforeBeginEnvironment{otoutput}{\begin{ot@outputbox}}
  \AfterEndEnvironment{otoutput}{\end{ot@outputbox}}
  \BeforeBeginEnvironment{verbatim}{\begin{ot@outputbox}}
  \AfterEndEnvironment{verbatim}{\end{ot@outputbox}}
\else
  % No tcolorbox: fall back to a plain left rule drawn by fancyvrb itself.
  \fvset{frame=leftline, framerule=2pt, rulecolor=\color{otaccentlt},
         framesep=7pt, xleftmargin=9pt}
\fi

%% ---------------------------------------------------------------- callouts ---
% \begin{otcaution}[Heading] ... \end{otcaution}
%   The epistemic caveats this project cares about (a sketch is not a proof, a
%   counterexample candidate is not a refutation) get a visible box instead of
%   a sentence buried in prose.
% \begin{otpanel} ... \end{otpanel}
%   Neutral tinted panel, used for the front-matter metadata strip.
\ifot@tcb
  \newenvironment{otcaution}[1][Note]{%
    \begin{tcolorbox}[enhanced, breakable, sharp corners,
      colback=otwarnbg, colframe=otwarnbg, boxrule=0pt,
      borderline west={2.5pt}{0pt}{otwarn},
      left=8pt, right=8pt, top=6pt, bottom=6pt,
      before skip=.8\baselineskip, after skip=.8\baselineskip]%
    {\sffamily\bfseries\footnotesize\color{otwarn}\MakeUppercase{#1}}\par
    \vspace{.25\baselineskip}\small\ignorespaces
  }{\end{tcolorbox}}
  \newenvironment{otpanel}{%
    \begin{tcolorbox}[enhanced, breakable, sharp corners,
      colback=otsurface, colframe=otrule, boxrule=.7pt,
      left=9pt, right=9pt, top=7pt, bottom=7pt,
      before skip=.9\baselineskip, after skip=.9\baselineskip]%
    \small\ignorespaces
  }{\end{tcolorbox}}
\else
  \newenvironment{otcaution}[1][Note]{%
    \par\medskip\noindent\textbf{#1.}\itshape\ignorespaces}{\par\medskip}
  \newenvironment{otpanel}{%
    \par\medskip\noindent\small\ignorespaces}{\par\medskip}
\fi

%% ----------------------------------------------------------------- inline ---
% Artifact identifiers: EXP-0001, PAPER-0007, CLAIM-0003 ...
\newcommand{\artifact}[1]{{\ttfamily\small\color{otaccent}\mbox{#1}}}
% Gap markers inside proof sketches: [GAP-1]
\newcommand{\gapmarker}[1]{{\ttfamily\small\color{otwarn}\mbox{#1}}}
% Status chips.
\newcommand{\otchip}[2]{%
  \colorbox{#1!12!white}{\textcolor{#1!85!black}{\scriptsize\sffamily\bfseries\,#2\,}}}
\newcommand{\statusbadge}[1]{\otchip{otmuted}{#1}}
\newcommand{\statusok}[1]{\otchip{otok}{#1}}
\newcommand{\statusbad}[1]{\otchip{otbad}{#1}}
\newcommand{\statuswarn}[1]{\otchip{otwarn}{#1}}

%% ------------------------------------------------------------------ links ---
\RequirePackage[colorlinks = true,
                linkcolor  = otaccent,
                citecolor  = otaccent,
                urlcolor   = otaccent,
                filecolor  = otaccent]{hyperref}

%% --------------------------------------------------------- front-matter kv ---
% \otdossierpanel{\otmeta{..}{..} & \otmeta{..}{..} & ...} -- metadata strip
% printed directly under \maketitle.
% Status values run up to "partially_resolved" / "solved_externally", and a chip
% is an unbreakable box — the columns are sized for the longest of them.
\newcommand{\otmeta}[2]{%
  \textcolor{otmuted}{\scriptsize\sffamily\MakeUppercase{#1}}\par
  \vspace{.2\baselineskip}#2}
\newcommand{\otdossierpanel}[1]{%
  \begin{otpanel}%
  \begin{tabularx}{\linewidth}%
    {@{}P{.185\linewidth}P{.20\linewidth}P{.18\linewidth}L@{}}#1\end{tabularx}%
  \end{otpanel}}

%% ------------------------------------------------------------ misc blocks ---
% The command line an experiment was run with.
\ifot@tcb
  \newcommand{\otruncmd}[1]{%
    \begin{tcolorbox}[enhanced, sharp corners, colback=otsurface,
      colframe=otsurface, boxrule=0pt,
      borderline west={2pt}{0pt}{otaccentlt},
      left=7pt, right=7pt, top=4pt, bottom=4pt,
      before skip=.6\baselineskip, after skip=.6\baselineskip]%
    {\ttfamily\small\textcolor{otmuted}{\$}\,#1}%
    \end{tcolorbox}}
\else
  \newcommand{\otruncmd}[1]{%
    \par\medskip\noindent{\ttfamily\small\textcolor{otmuted}{\$}\,#1}\par\medskip}
\fi

% Compact comma-separated artifact roll-up (a 40-item itemize wastes a page).
\newcommand{\otartifactindex}[1]{{\raggedright\small #1\par}}

\endinput
