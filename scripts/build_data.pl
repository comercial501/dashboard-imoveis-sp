#!/usr/bin/perl
# Builds data/dashboard_data.json from the raw ITBI (Prefeitura) and Usenonstop
# spreadsheets. See /Users/plaghi/.claude/plans/misty-frolicking-hejlsberg.md
# for the full methodology this script implements.
use strict;
use warnings;
use utf8;
use FindBin qw($Bin);
use lib $Bin;
use XlsxExtract qw(read_shared_strings read_sheet_rows read_workbook_sheets);
use JSON::PP;
use Time::Local qw(timegm);

binmode(STDOUT, ':encoding(UTF-8)');
binmode(STDERR, ':encoding(UTF-8)');

my $ROOT     = "$Bin/..";
my $PREF_DIR = "$ROOT/dados-prefeitura";
my $USN_DIR  = "$ROOT/dados-usenonstop";
my $OUT_FILE = "$ROOT/data/dashboard_data.json";

# ---------------------------------------------------------------------------
# 1) Canonical target neighborhoods + normalization
# ---------------------------------------------------------------------------

my @TARGETS = (
    'Vila Madalena', 'Lapa', 'Pinheiros', 'Itaim Bibi', 'Vila Olímpia', 'Brooklin',
    'Chácara Santo Antônio', 'Alto da Boa Vista', 'Jardim dos Estados', 'Jardim Petrópolis',
    'Vila Cordeiro', 'Jardim Caravelas', 'Jardim Santo Amaro', 'Campo Belo', 'Indianópolis',
    'Jardim Novo Mundo', 'Moema', 'Vila Uberabinha', 'Vila Nova Conceição', 'Jardim Europa',
    'Jardins', 'Jardim Paulista', 'Ibirapuera', 'Jardim das Bandeiras', 'Sumaré', 'Pacaembu',
    'Higienópolis', 'Perdizes', 'Pompéia', 'Santa Cecília', 'Consolação', 'Bela Vista',
    'Paraíso', 'Planalto Paulista', 'Mirandópolis', 'Chácara Inglesa', 'Bosque da Saúde',
    'Vila Mariana', 'Jardim Vila Mariana', 'Vila Gumercindo', 'Vila Firmiano Pinto',
    'Jardim da Glória', 'Cambuci', 'Vila da Saúde', 'Ipiranga', 'Mooca', 'Tatuapé',
);

# Approved merges (normalized-variant => normalized-canonical). See plan doc section 1.
my %ALIASES = (
    'BROOKLIN PAULISTA' => 'BROOKLIN',
    'BROOKLIN NOVO'     => 'BROOKLIN',
    'VILA POMPEIA'      => 'POMPEIA',
);

my %ACCENTS = (
    'Á'=>'A','À'=>'A','Ã'=>'A','Â'=>'A','Ä'=>'A',
    'É'=>'E','È'=>'E','Ê'=>'E','Ë'=>'E',
    'Í'=>'I','Ì'=>'I','Î'=>'I','Ï'=>'I',
    'Ó'=>'O','Ò'=>'O','Õ'=>'O','Ô'=>'O','Ö'=>'O',
    'Ú'=>'U','Ù'=>'U','Û'=>'U','Ü'=>'U',
    'Ç'=>'C','Ñ'=>'N',
);

sub normalize_bairro {
    my ($s) = @_;
    return '' unless defined $s;
    $s = uc($s);
    $s =~ s/\([^)]*\)//g;   # parenthetical annotations, e.g. "(Zona Sul)"
    $s =~ s/"[^"]*"//g;     # quoted annotations, e.g. "MOBILIADO"
    for my $k (keys %ACCENTS) { $s =~ s/\Q$k\E/$ACCENTS{$k}/g; }
    $s =~ s/[^A-Z0-9\s]//g;
    $s =~ s/\s+/ /g;
    $s =~ s/^\s+|\s+$//g;
    return $s;
}

my %CANON_BY_NORM;
for my $t (@TARGETS) { $CANON_BY_NORM{normalize_bairro($t)} = $t; }

sub bairro_canon {
    my ($raw) = @_;
    my $n = normalize_bairro($raw);
    return undef unless length($n);
    $n = $ALIASES{$n} if exists $ALIASES{$n};
    return $CANON_BY_NORM{$n};
}

# ---------------------------------------------------------------------------
# Mudança 2: address normalization (ITBI "Nome do Logradouro" is abbreviated
# by the city's own system; Usenonstop's "Endereço" is spelled out) so the two
# sides join on the same key: bairro | rua normalizada | número.
# ---------------------------------------------------------------------------

my %STREET_ABBR = (
    R => 'RUA', AV => 'AVENIDA', AL => 'ALAMEDA', PC => 'PRACA', PCA => 'PRACA',
    ES => 'ESTRADA', EST => 'ESTRADA', TV => 'TRAVESSA', VD => 'VIADUTO',
    LG => 'LARGO', PQ => 'PARQUE', PRQ => 'PARQUE', ROD => 'RODOVIA', RV => 'RODOVIA',
);

sub normalize_street {
    my ($s) = @_;
    return '' unless defined $s;
    $s = uc($s);
    for my $k (keys %ACCENTS) { $s =~ s/\Q$k\E/$ACCENTS{$k}/g; }
    $s =~ s/[^A-Z0-9\s]//g;
    $s =~ s/\s+/ /g;
    $s =~ s/^\s+|\s+$//g;
    my @tokens = split(/ /, $s);
    if (@tokens && exists $STREET_ABBR{$tokens[0]}) { $tokens[0] = $STREET_ABBR{$tokens[0]}; }
    return join(' ', @tokens);
}

sub normalize_number {
    my ($s) = @_;
    return '' unless defined $s;
    $s =~ s/\.0+$//;
    $s =~ s/^\s+|\s+$//g;
    $s =~ s/^0+(?=\d)//; # strip leading zeros, keep a lone "0"
    return $s;
}

sub address_key {
    my ($bairro, $street, $number) = @_;
    my $s = normalize_street($street);
    my $n = normalize_number($number);
    return undef unless length($s) && length($n);
    return "$bairro|$s|$n";
}

sub display_street {
    # Title-case just for display (e.g. "RUA APINAJES" -> "Rua Apinajes").
    my ($s) = @_;
    return join(' ', map { ucfirst(lc($_)) } split(/ /, $s));
}

# ---------------------------------------------------------------------------
# 2) Small stats helpers
# ---------------------------------------------------------------------------

sub mean {
    return undef unless @_;
    my $s = 0; $s += $_ for @_;
    return $s / scalar(@_);
}

sub median {
    my @v = sort { $a <=> $b } @_;
    return undef unless @v;
    my $n = scalar @v;
    return $n % 2 ? $v[int($n/2)] : ($v[$n/2 - 1] + $v[$n/2]) / 2;
}

sub percentile {
    my ($p, @v) = @_;
    @v = sort { $a <=> $b } @v;
    return undef unless @v;
    my $idx = $p / 100 * (scalar(@v) - 1);
    my $lo = int($idx); my $frac = $idx - $lo;
    my $hi = $lo + 1 < scalar(@v) ? $lo + 1 : $lo;
    return $v[$lo] + ($v[$hi] - $v[$lo]) * $frac;
}

my $MAX_PER_EXACT_AREA = 5;

sub dedup_cap_exact_area {
    # The city's "Área Construída" field sometimes carries a default/placeholder
    # value shared by hundreds of unrelated rows on the same street (observed
    # e.g. ~200 rows all at exactly 320/320.0 m2 on "AV POMPEIA" with no building
    # reference) instead of a real per-unit measurement. A real, organically
    # varying dataset shouldn't have hundreds of exact ties, so cap how many
    # rows any single exact area value may contribute before computing the mode.
    my ($pairs) = @_;
    my %seen;
    my @out;
    for my $p (@$pairs) {
        my $key = sprintf('%.2f', $p->{area});
        $seen{$key}++;
        push @out, $p if $seen{$key} <= $MAX_PER_EXACT_AREA;
    }
    return \@out;
}

sub mode_bucket_from_pairs {
    # returns (lo, hi, list-of-valores-in-band) for the most frequent area bucket
    my ($raw_pairs, $width) = @_;
    my $pairs = dedup_cap_exact_area($raw_pairs);
    return (undef, undef, []) unless @$pairs;
    my %counts;
    for my $p (@$pairs) { $counts{ int($p->{area} / $width) }++; }
    # Deterministic tie-break (smallest bucket wins) so this doesn't depend on
    # Perl's hash iteration order -- matters for byte-for-byte agreement with
    # the JavaScript port (Mudança 8), which must reproduce ties the same way.
    my ($best_b) = sort { $counts{$b} <=> $counts{$a} || $a <=> $b } keys %counts;
    my ($lo, $hi) = ($best_b * $width, ($best_b + 1) * $width);
    my @valores = map { $_->{valor} } grep { $_->{area} >= $lo && $_->{area} < $hi } @$pairs;
    return ($lo, $hi, \@valores);
}

sub mode_of {
    return undef unless @_;
    my %c; $c{$_}++ for @_;
    # Deterministic tie-break (smallest value wins) -- see mode_bucket_from_pairs.
    my ($best) = sort { $c{$b} <=> $c{$a} || $a <=> $b } keys %c;
    return $best;
}

sub zscore_map {
    my (%vals) = @_; # key => number (may include undef)
    my @nums = grep { defined $_ } values %vals;
    return map { $_ => 0 } keys %vals unless @nums >= 2;
    my $m = mean(@nums);
    my $var = mean(map { ($_ - $m) ** 2 } @nums);
    my $sd = sqrt($var) || 1;
    my %z;
    for my $k (keys %vals) {
        $z{$k} = defined $vals{$k} ? ($vals{$k} - $m) / $sd : -2; # missing data -> treat as low
    }
    return %z;
}

# z-score -> min-max rescale para 0-100, mesmo método usado no score do Painel 1.
sub normalize_0_100 {
    my (%raw) = @_;
    my %z = zscore_map(%raw);
    my @vals = values %z;
    my ($mn, $mx) = (percentile(0, @vals), percentile(100, @vals));
    my $range = ($mx - $mn) || 1;
    my %out;
    for my $k (keys %z) { $out{$k} = (($z{$k} - $mn) / $range) * 100; }
    return %out;
}

# Excel serial date (1900 system, epoch 1899-12-30 handles the classic leap-year bug) -> (year, month)
my $EXCEL_EPOCH = timegm(0, 0, 0, 30, 11, 1899);
sub excel_serial_to_ym {
    my ($serial) = @_;
    return (undef, undef) unless defined $serial && $serial =~ /^\d+(\.\d+)?$/;
    my $secs = $EXCEL_EPOCH + int($serial) * 86400;
    my @t = gmtime($secs);
    return ($t[5] + 1900, $t[4] + 1);
}

# ---------------------------------------------------------------------------
# 3) Parse ITBI (Prefeitura) files
# ---------------------------------------------------------------------------

my $AREA_CAP = 600;  # m2 — see comment below on the "área construída" data artifact
my $TREND_CAP = 1.0; # ±100% — caps runaway % growth from tiny-base bairros before scoring

# ---------------------------------------------------------------------------
# Mudança 7: discover source files by content, not by filename. Any .xlsx in
# dados-prefeitura/ is scanned for sheets named MES-ANO (e.g. "JAN-2024"); each
# one found contributes that month, regardless of what the file itself is
# called. If two files claim the same month, the one with the newer filesystem
# mtime wins and a warning is recorded (surfaced by atualizar.sh).
# ---------------------------------------------------------------------------

my %MONTH_NUM = (JAN=>1, FEV=>2, MAR=>3, ABR=>4, MAI=>5, JUN=>6, JUL=>7, AGO=>8, SET=>9, OUT=>10, NOV=>11, DEZ=>12);

my @discovery_warnings;

sub discover_itbi_sources {
    my ($dir) = @_;
    my %period; # {year}{month} = { file, target, mtime, display }
    opendir(my $dh, $dir) or die "nao consegui abrir $dir: $!";
    my @files = sort grep { /\.xlsx$/i && -f "$dir/$_" } readdir($dh);
    closedir($dh);
    die "Nenhum arquivo .xlsx encontrado em $dir" unless @files;

    for my $fname (@files) {
        my $path = "$dir/$fname";
        my $mtime = (stat($path))[9];
        my $sheets = read_workbook_sheets($path);
        my $found_any = 0;
        for my $s (@$sheets) {
            next unless $s->{name} =~ /^(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)-(\d{4})$/;
            my ($mes, $year) = ($1, $2 + 0);
            my $month = $MONTH_NUM{$mes};
            $found_any = 1;
            my $existing = $period{$year}{$month};
            if (!$existing) {
                $period{$year}{$month} = { file => $path, target => $s->{target}, mtime => $mtime, display => $fname };
            } elsif ($mtime > $existing->{mtime}) {
                push @discovery_warnings, sprintf('Periodo %s-%d duplicado: usando "%s" (mais recente) em vez de "%s"', $mes, $year, $fname, $existing->{display});
                $period{$year}{$month} = { file => $path, target => $s->{target}, mtime => $mtime, display => $fname };
            } elsif ($mtime < $existing->{mtime}) {
                push @discovery_warnings, sprintf('Periodo %s-%d duplicado: mantendo "%s" (mais recente) em vez de "%s"', $mes, $year, $existing->{display}, $fname);
            } else {
                push @discovery_warnings, sprintf('Periodo %s-%d duplicado em "%s" e "%s" com a mesma data de modificacao: mantendo "%s"', $mes, $year, $fname, $existing->{display}, $existing->{display});
            }
        }
        push @discovery_warnings, qq{Arquivo "$fname" nao tem nenhuma aba MES-ANO (ex: JAN-2024) - ignorado como fonte de transacoes}
            unless $found_any;
    }
    return \%period;
}

my $USN_HEADER_HINTS = [qw(Código Endereço Bairro Cidade Situação)];

sub discover_usenonstop_source {
    my ($dir) = @_;
    opendir(my $dh, $dir) or die "nao consegui abrir $dir: $!";
    my @files = sort grep { /\.xlsx$/i && -f "$dir/$_" } readdir($dh);
    closedir($dh);
    die "Nenhum arquivo .xlsx encontrado em $dir" unless @files;

    my @candidates;
    for my $fname (@files) {
        my $path = "$dir/$fname";
        my $sheets = read_workbook_sheets($path);
        next unless @$sheets;
        my $target = $sheets->[0]{target};
        my $shared = read_shared_strings($path); # empty arrayref if no sharedStrings.xml (inline strings)
        my %header;
        read_sheet_rows($path, $target, $shared, sub {
            my ($rnum, $cells) = @_;
            return unless $rnum == 1;
            %header = map { (defined $_ ? ($_ => 1) : ()) } values %$cells;
        });
        my $hits = grep { $header{$_} } @$USN_HEADER_HINTS;
        if ($hits >= 4) {
            push @candidates, { file => $path, target => $target, mtime => (stat($path))[9], display => $fname };
        } else {
            push @discovery_warnings, qq{Arquivo "$fname" nao parece ser a planilha de estoque da Usenonstop (cabecalho nao bateu) - ignorado};
        }
    }
    die "Nenhum arquivo em $dir foi reconhecido como planilha de estoque da Usenonstop" unless @candidates;
    @candidates = sort { $b->{mtime} <=> $a->{mtime} } @candidates;
    my $chosen = $candidates[0];
    for my $other (@candidates[1..$#candidates]) {
        push @discovery_warnings, sprintf('Mais de um arquivo de estoque Usenonstop encontrado: usando "%s" (mais recente) em vez de "%s"', $chosen->{display}, $other->{display});
    }
    return $chosen;
}

my $itbi_periods = discover_itbi_sources($PREF_DIR);
my $usn_source   = discover_usenonstop_source($USN_DIR);

if (@discovery_warnings) {
    print STDERR "\n=== Avisos da descoberta de arquivos ===\n";
    print STDERR "  - $_\n" for @discovery_warnings;
    print STDERR "\n";
}

# itbi{bairro}{year} = { count, pairs => [ {area, valor}, ... ] (only rows with both) }
# itbi_month{bairro}{"YYYY-MM"} = count
# itbi_addr{"bairro|rua|numero"} = [ {year, day (excel serial), valor}, ... ] -- Mudança 2
my %itbi;
my %itbi_month;
my %itbi_addr;
my ($total_rows_seen, $total_rows_matched) = (0, 0);
my %shared_cache;

# ---------------------------------------------------------------------------
# Mudança 8: raw-record export (bairro dictionary + shared address dictionary
# + compact per-transaction/per-listing arrays) so the browser can recompute
# the whole methodology client-side under a bairro/price filter. This runs
# alongside (not instead of) the aggregation above, which stays untouched and
# keeps feeding compare_runs.pl / atualizar.sh's week-over-week diff, and also
# serves as the reference this export is verified against (see verify_raw.pl).
# ---------------------------------------------------------------------------

my %bairro_index; my $bi = 0; $bairro_index{$_} = $bi++ for @TARGETS;

my %addr_index;   # normalized "bairro|rua|numero" -> integer index
my @addr_display; # index -> "Rua X, 969" for display

sub addr_idx_for {
    my ($key, $display) = @_;
    return undef unless defined $key;
    if (!exists $addr_index{$key}) {
        $addr_index{$key} = scalar(@addr_display);
        push @addr_display, $display;
    }
    return $addr_index{$key};
}
sub addr_upgrade_display {
    my ($key, $display) = @_;
    return unless defined $key && exists $addr_index{$key} && defined $display && length($display);
    $addr_display[ $addr_index{$key} ] = $display;
}

my %SITUACAO_CODE = (PADRAO => 0, NOVO => 1, REFORMA => 2, LANCAMENTO => 3, CONSTRUCAO => 4);

# itbi_raw[] = [bairro_idx, sheet_year, day(excel serial) or null, valor, area(capped, >0) or null, addr_idx or null]
# usn_raw[]  = [bairro_idx, addr_idx or null, endereco_completo, valor or null, area or null,
#               quartos or null, vagas or null, lat or null, lon or null, situacao_code, codigo or null, link or null]
# endereco_completo is stored pre-built (not reconstructed from the address
# dictionary) because address_key() requires both street AND number to be
# present, while the display string only needs the street -- a listing with a
# street but no number would silently lose its street name if reconstructed
# from addr_idx alone.
my @itbi_raw;
my @usn_raw;

for my $year (sort keys %$itbi_periods) {
    for my $month (sort { $a <=> $b } keys %{ $itbi_periods->{$year} }) {
        my $src = $itbi_periods->{$year}{$month};
        my $file = $src->{file};
        print STDERR "Lendo ITBI $month/$year: $src->{display} ($src->{target})\n";
        $shared_cache{$file} //= read_shared_strings($file);
        my $shared = $shared_cache{$file};
        read_sheet_rows($file, $src->{target}, $shared, sub {
            my ($rnum, $cells) = @_;
            $total_rows_seen++;
            my $raw_bairro = $cells->{E};
            return unless defined $raw_bairro;
            my $canon = bairro_canon($raw_bairro);
            return unless defined $canon;
            # Restrict to residential-dwelling "Uso (IPTU)" codes (col X): plain
            # residências, apartamentos em condomínio and residential flats. This
            # matters a lot: about half of all ITBI rows are garagens (unidade
            # autônoma, código 23/24/62/63), terrenos (0) or non-residential uses,
            # and mixing those into the median "valor pago" understates it hugely
            # (e.g. Moema 2025 median goes from R$450k with everything included to
            # R$840k restricted to residências/apartamentos) versus what Usenonstop
            # actually advertises (whole homes, not parking spots or land).
            my $uso = $cells->{X};
            return unless defined $uso && $uso =~ /^(?:10|12|14|20|21|22|25)(?:\.0+)?$/;
            my $valor = $cells->{I};
            my $data  = $cells->{J};
            my $area  = $cells->{W};
            return unless defined $valor && $valor =~ /^-?\d+(\.\d+)?$/ && $valor + 0 > 0;
            $total_rows_matched++;

            $itbi{$canon}{$year}{count}++;
            push @{ $itbi{$canon}{$year}{valores} }, $valor + 0;
            # "Área Construída" has a known data-quality issue in this dataset: for a
            # sizeable share of rows (~16% citywide) it holds the *whole building's*
            # constructed area instead of the individual unit's (e.g. clusters of
            # hundreds of transactions all sharing one implausible value like 3600m2
            # or 33820m2). Cap at AREA_CAP so those don't win the area-band mode.
            if (defined $area && $area =~ /^-?\d+(\.\d+)?$/ && $area + 0 > 0 && $area + 0 <= $AREA_CAP) {
                push @{ $itbi{$canon}{$year}{pairs} }, { area => $area + 0, valor => $valor + 0 };
            }

            my ($y, $m) = excel_serial_to_ym($data);
            if (defined $y) {
                $itbi_month{$canon}{ sprintf('%04d-%02d', $y, $m) }{count}++;
            }

            my $akey = address_key($canon, $cells->{B}, $cells->{C});
            if (defined $akey && $data =~ /^\d+(\.\d+)?$/) {
                # área sujeita ao mesmo AREA_CAP usado no perfil vencedor (linha ~423)
                # -- mesmo problema de qualidade de dado (área do prédio inteiro em vez
                # da unidade) se aplica aqui, na faixa de metragem por endereço.
                my $addr_area = (defined $area && $area =~ /^-?\d+(\.\d+)?$/ && $area + 0 > 0 && $area + 0 <= $AREA_CAP) ? $area + 0 : undef;
                push @{ $itbi_addr{$akey} }, { year => $year, day => int($data), valor => $valor + 0, area => $addr_area };
            }

            my $addr_idx;
            if (defined $akey) {
                my (undef, $street_norm, $num_norm) = split(/\|/, $akey, 3);
                $addr_idx = addr_idx_for($akey, display_street($street_norm) . ', ' . $num_norm);
            }
            push @itbi_raw, [
                $bairro_index{$canon},
                $year + 0, # sheet year (which yearly{} bucket this counts toward) -- NOT re-derived
                          # from $data client-side, because a transaction's own date can, in rare
                          # cases, fall outside its containing sheet's nominal month/year.
                ($data =~ /^\d+(\.\d+)?$/ ? int($data) : undef), # excel serial day, for month/launch calcs
                $valor + 0,
                (defined $area && $area =~ /^-?\d+(\.\d+)?$/ && $area + 0 > 0 && $area + 0 <= $AREA_CAP ? $area + 0 : undef),
                $addr_idx,
            ];
        });
    }
    print STDERR "  $year concluido. linhas acumuladas=$total_rows_seen match=$total_rows_matched\n";
}

# ---------------------------------------------------------------------------
# 4) Parse Usenonstop (current stock, "VENDA" listings only)
# ---------------------------------------------------------------------------

print STDERR "Lendo Usenonstop: $usn_source->{display} ($usn_source->{target})\n";

my %usn; # bairro => arrayref of { valor, area, vagas, quartos, lat, lon }
# usn_addr{"bairro|rua|numero"} = arrayref of { situacao, valor, codigo, link, rua_display, numero } -- Mudança 2
my %usn_addr;
my ($usn_rows_seen, $usn_rows_matched) = (0, 0);

{
    my $shared = read_shared_strings($usn_source->{file}); # empty if inline "str" cells (no sharedStrings.xml)
    read_sheet_rows($usn_source->{file}, $usn_source->{target}, $shared, sub {
        my ($rnum, $cells) = @_;
        return if $rnum == 1; # header
        $usn_rows_seen++;
        my $raw_bairro = $cells->{F};
        return unless defined $raw_bairro;
        my $disp = $cells->{J} // '';
        return unless $disp =~ /VENDA/i;
        my $uso = $cells->{O} // '';
        return unless $uso =~ /^RESIDENCIAL$/i; # exclude COMERCIAL/RURAL/INDUSTRIAL/LOGISTICO listings
        my $canon = bairro_canon($raw_bairro);
        return unless defined $canon;
        $usn_rows_matched++;

        my $valor   = $cells->{K};
        my $area    = $cells->{Q};
        my $vagas   = $cells->{T};
        my $quartos = $cells->{X};
        my $coords  = $cells->{I} // '';

        my ($lat, $lon);
        if ($coords =~ /lat:\s*(-?\d+\.?\d*),\s*lng:\s*(-?\d+\.?\d*)/) {
            # Labels are swapped in the source file (confirmed on ~99.99% of rows):
            # the "lat:" value is actually the longitude and vice-versa.
            ($lon, $lat) = ($1 + 0, $2 + 0);
        }

        my $akey = address_key($canon, $cells->{C}, $cells->{D});
        my $endereco_completo = defined($cells->{C}) ? $cells->{C} : '';
        $endereco_completo .= ', ' . $cells->{D} if defined $cells->{D} && length($cells->{D});
        $endereco_completo .= ' - ' . $cells->{E} if defined $cells->{E} && length($cells->{E});

        my $addr_idx;
        if (defined $akey) {
            my $usn_display = $cells->{C} // '';
            $usn_display .= ', ' . $cells->{D} if defined $cells->{D} && length($cells->{D});
            my (undef, $street_norm, $num_norm) = split(/\|/, $akey, 3);
            $addr_idx = addr_idx_for($akey, display_street($street_norm) . ', ' . $num_norm);
            addr_upgrade_display($akey, $usn_display); # prefer Usenonstop's natural spelling/casing when available
        }
        my $situacao_raw = uc($cells->{V} // '');
        push @usn_raw, [
            $bairro_index{$canon},
            $addr_idx,
            $endereco_completo,
            (defined $valor   && $valor   =~ /^-?\d+(\.\d+)?$/) ? $valor + 0   : undef,
            (defined $area    && $area    =~ /^-?\d+(\.\d+)?$/) ? $area + 0    : undef,
            (defined $quartos && $quartos =~ /^-?\d+$/)          ? $quartos + 0 : undef,
            (defined $vagas   && $vagas   =~ /^-?\d+$/)          ? $vagas + 0   : undef,
            $lat, $lon,
            $SITUACAO_CODE{$situacao_raw} // 0,
            $cells->{B}, # codigo
            $cells->{BA}, # link
        ];

        push @{ $usn{$canon} }, {
            valor   => (defined $valor   && $valor   =~ /^-?\d+(\.\d+)?$/) ? $valor + 0   : undef,
            area    => (defined $area    && $area    =~ /^-?\d+(\.\d+)?$/) ? $area + 0    : undef,
            vagas   => (defined $vagas   && $vagas   =~ /^-?\d+$/)          ? $vagas + 0   : undef,
            quartos => (defined $quartos && $quartos =~ /^-?\d+$/)          ? $quartos + 0 : undef,
            lat => $lat, lon => $lon,
            addr_key => $akey,
            endereco => $endereco_completo,
            codigo   => $cells->{B},
            link     => $cells->{BA},
        };

        if (defined $akey) {
            push @{ $usn_addr{$akey} }, {
                situacao => uc($cells->{V} // ''),
                valor    => (defined $valor && $valor =~ /^-?\d+(\.\d+)?$/) ? $valor + 0 : undef,
                codigo   => $cells->{B},
                link     => $cells->{BA},
                rua_display => $cells->{C},
                numero      => $cells->{D},
            };
        }
    });
}
print STDERR "Usenonstop: linhas vistas=$usn_rows_seen match(bairro-alvo e VENDA)=$usn_rows_matched\n";

sub coord_is_valid_sp {
    my ($lat, $lon) = @_;
    return 0 unless defined $lat && defined $lon;
    return $lat >= -24.2 && $lat <= -23.0 && $lon >= -47.0 && $lon <= -46.2;
}

# Great-circle distance in km, used to find geographic neighbors for the
# low-sample regional fallback (Mudança 1).
sub haversine_km {
    my ($lat1, $lon1, $lat2, $lon2) = @_;
    my $R = 6371;
    my $rad = 3.14159265358979 / 180;
    my $dlat = ($lat2 - $lat1) * $rad;
    my $dlon = ($lon2 - $lon1) * $rad;
    my $a = sin($dlat/2)**2 + cos($lat1*$rad) * cos($lat2*$rad) * sin($dlon/2)**2;
    my $c = 2 * atan2(sqrt($a), sqrt(1 - $a));
    return $R * $c;
}

# Returns up to $count nearest target bairros (by centroid distance, within
# $max_km) to $bairro, as a list of [name, distance_km], nearest first.
# $base_ref must already have centroids populated for every bairro.
sub nearest_neighbors {
    my ($bairro, $base_ref, $targets_ref, $max_km, $count) = @_;
    my $c0 = $base_ref->{$bairro}{centroid};
    return () unless $c0;
    my @dists;
    for my $other (@$targets_ref) {
        next if $other eq $bairro;
        my $c1 = $base_ref->{$other}{centroid};
        next unless $c1;
        push @dists, [$other, haversine_km($c0->[0], $c0->[1], $c1->[0], $c1->[1])];
    }
    @dists = sort { $a->[1] <=> $b->[1] } grep { $_->[1] <= $max_km } @dists;
    splice(@dists, $count) if @dists > $count;
    return @dists;
}

# ---------------------------------------------------------------------------
# 5) Per-bairro aggregation
# ---------------------------------------------------------------------------

my $AREA_BUCKET_WIDTH = 20; # m2

# Mudança 1: below this many samples, an individually-computed area/price band
# or dormitórios/vagas mode is considered too thin to trust on its own and
# falls back to a regional estimate pooled from nearby target bairros.
my $RELIABILITY_THRESHOLD = 5;
my $NEIGHBOR_MAX_KM = 3;
my $NEIGHBOR_COUNT = 3;

my %base; # bairro => base stats (before cross-bairro scoring)

for my $bairro (@TARGETS) {
    my $itbi_b = $itbi{$bairro} // {};
    my $listings = $usn{$bairro} // [];

    my %yearly;
    for my $year (2024, 2025, 2026) {
        my $y = $itbi_b->{$year} // {};
        my @valores = @{ $y->{valores} // [] };
        $yearly{$year} = {
            count        => $y->{count} // 0,
            avg_valor    => mean(@valores),
            median_valor => median(@valores),
        };
    }

    my $growth_24_25;
    $growth_24_25 = ($yearly{2025}{count} - $yearly{2024}{count}) / $yearly{2024}{count}
        if $yearly{2024}{count} > 0;

    my ($h1_2025, $h1_2026) = (0, 0);
    for my $m (1..6) {
        $h1_2025 += ($itbi_month{$bairro}{ sprintf('2025-%02d', $m) }{count} // 0);
        $h1_2026 += ($itbi_month{$bairro}{ sprintf('2026-%02d', $m) }{count} // 0);
    }
    my $growth_h1;
    $growth_h1 = ($h1_2026 - $h1_2025) / $h1_2025 if $h1_2025 > 0;

    my @growths = grep { defined $_ } ($growth_24_25, $growth_h1);
    my $trend_pct = @growths ? mean(@growths) : undef;
    # Bairros with a tiny 2024 base (e.g. 8 -> 203 transactions) can post
    # percentage growth in the thousands and would otherwise swamp the z-score
    # for every other bairro. Cap the value used for *scoring* only; the raw
    # trend_pct is still reported as-is in the JSON for transparency.
    my $trend_pct_for_score = defined $trend_pct
        ? ($trend_pct > $TREND_CAP ? $TREND_CAP : ($trend_pct < -$TREND_CAP ? -$TREND_CAP : $trend_pct))
        : undef;

    # Perfil vencedor: dominant area band (all years) + price band of transactions in it.
    my @all_pairs = map { @{ $itbi_b->{$_}{pairs} // [] } } (2024, 2025, 2026);
    my ($area_lo, $area_hi, $valores_in_band) = mode_bucket_from_pairs(\@all_pairs, $AREA_BUCKET_WIDTH);
    my $price_p25 = percentile(25, @$valores_in_band);
    my $price_p75 = percentile(75, @$valores_in_band);
    my $price_median_band = median(@$valores_in_band);

    # Usenonstop stock matching that area band -> mode of quartos/vagas (the "combo" to advertise)
    my @matching = defined $area_lo
        ? grep { defined $_->{area} && $_->{area} >= $area_lo && $_->{area} < $area_hi } @$listings
        : ();
    my @quartos_vals = grep { defined $_ } map { $_->{quartos} } @matching;
    my @vagas_vals   = grep { defined $_ } map { $_->{vagas} } @matching;
    my $profile_quartos = mode_of(@quartos_vals);
    my $profile_vagas   = mode_of(@vagas_vals);
    my $profile_sample_size = scalar(@matching);

    # Estoque atual (todas as faixas) para o painel de preco e estoque geral
    my @asking_valores = grep { defined $_ } map { $_->{valor} } @$listings;
    my $asking_median = median(@asking_valores);

    # Centroid from valid coordinates
    my @valid_coords = grep { coord_is_valid_sp($_->{lat}, $_->{lon}) } @$listings;
    my $centroid_lat = mean(map { $_->{lat} } @valid_coords);
    my $centroid_lon = mean(map { $_->{lon} } @valid_coords);

    $base{$bairro} = {
        yearly              => \%yearly,
        growth_24_25        => $growth_24_25,
        growth_h1           => $growth_h1,
        trend_pct           => $trend_pct,
        trend_pct_for_score => $trend_pct_for_score,
        volume_2025         => $yearly{2025}{count},
        area_band           => (defined $area_lo ? [$area_lo + 0, $area_hi + 0] : undef),
        price_band          => (defined $price_p25 ? [$price_p25 + 0, $price_p75 + 0] : undef),
        price_band_median   => $price_median_band,
        profile_quartos     => $profile_quartos,
        profile_vagas       => $profile_vagas,
        profile_sample_size => $profile_sample_size,
        stock_total         => scalar(@$listings),
        stock_matching_profile => scalar(@matching),
        asking_median_valor => $asking_median,
        paid_median_valor_2025 => $yearly{2025}{median_valor},
        centroid            => (defined $centroid_lat ? [$centroid_lat + 0, $centroid_lon + 0] : undef),
    };
}

# ---------------------------------------------------------------------------
# 5b) Mudança 1: regional fallback for bairros with a thin individual sample.
#
# Two independent gates, both using $RELIABILITY_THRESHOLD:
#  - area/price band: needs >= threshold ITBI (area, valor) pairs of its own;
#    below that, pool ITBI pairs from the nearest target bairros (haversine
#    distance between Usenonstop-derived centroids, <= NEIGHBOR_MAX_KM, up to
#    NEIGHBOR_COUNT neighbors) and recompute the band from the combined pool.
#  - dormitórios/vagas: recomputed first against the (possibly-updated) area
#    band using ONLY the bairro's own Usenonstop stock -- this is also what
#    Painel 3 (Estoque x Demanda) uses, so it must stay scoped to that bairro's
#    real inventory. Only the dormitórios/vagas *mode* itself falls back to a
#    neighbor-pooled estimate (clearly flagged) when that own count is still
#    below threshold; Painel 3's counts are never inflated with neighbors' stock.
# ---------------------------------------------------------------------------

for my $bairro (@TARGETS) {
    my $b = $base{$bairro};

    my @own_pairs = map { @{ $itbi{$bairro}{$_}{pairs} // [] } } (2024, 2025, 2026);
    $b->{area_band_reliability} = (scalar(@own_pairs) >= $RELIABILITY_THRESHOLD) ? 'individual' : 'insufficient';
    $b->{area_band_neighbors} = [];

    if (scalar(@own_pairs) < $RELIABILITY_THRESHOLD) {
        my @neighbors = nearest_neighbors($bairro, \%base, \@TARGETS, $NEIGHBOR_MAX_KM, $NEIGHBOR_COUNT);
        if (@neighbors) {
            my @pooled_pairs = @own_pairs;
            my @nb_info;
            for my $nb (@neighbors) {
                my ($nbname, $dist) = @$nb;
                my @nb_pairs = map { @{ $itbi{$nbname}{$_}{pairs} // [] } } (2024, 2025, 2026);
                push @pooled_pairs, @nb_pairs;
                push @nb_info, { bairro => $nbname, distancia_km => sprintf('%.2f', $dist) + 0, n_pares => scalar(@nb_pairs) };
            }
            my ($lo, $hi, $vals) = mode_bucket_from_pairs(\@pooled_pairs, $AREA_BUCKET_WIDTH);
            if (defined $lo && @$vals) {
                $b->{area_band} = [$lo + 0, $hi + 0];
                $b->{price_band} = [percentile(25, @$vals) + 0, percentile(75, @$vals) + 0];
                $b->{price_band_median} = median(@$vals);
                $b->{area_band_reliability} = 'regional';
                $b->{area_band_neighbors} = \@nb_info;
            }
        }
    }

    # Re-score the bairro's OWN stock against the (possibly regional) area band.
    # This is the number Painel 3 (Estoque x Demanda) reads, so it must reflect
    # only this bairro's real inventory, never neighbors' listings.
    if ($b->{area_band}) {
        my ($lo, $hi) = @{ $b->{area_band} };
        my @own_matching = grep { defined $_->{area} && $_->{area} >= $lo && $_->{area} < $hi } @{ $usn{$bairro} // [] };
        $b->{profile_sample_size} = scalar(@own_matching);
        $b->{stock_matching_profile} = scalar(@own_matching);
        $b->{profile_quartos} = mode_of(grep { defined $_ } map { $_->{quartos} } @own_matching);
        $b->{profile_vagas}   = mode_of(grep { defined $_ } map { $_->{vagas} } @own_matching);
    }

    $b->{profile_reliability} = (($b->{profile_sample_size} // 0) >= $RELIABILITY_THRESHOLD) ? 'individual' : 'insufficient';
    $b->{profile_neighbors} = [];
    $b->{profile_pool_sample_size} = $b->{profile_sample_size};

    if (($b->{profile_sample_size} // 0) < $RELIABILITY_THRESHOLD && $b->{area_band}) {
        my @neighbors = nearest_neighbors($bairro, \%base, \@TARGETS, $NEIGHBOR_MAX_KM, $NEIGHBOR_COUNT);
        if (@neighbors) {
            my ($lo, $hi) = @{ $b->{area_band} };
            my @pool = grep { defined $_->{area} && $_->{area} >= $lo && $_->{area} < $hi } @{ $usn{$bairro} // [] };
            my @nb_info;
            for my $nb (@neighbors) {
                my ($nbname, $dist) = @$nb;
                my @nb_listings = grep { defined $_->{area} && $_->{area} >= $lo && $_->{area} < $hi } @{ $usn{$nbname} // [] };
                push @pool, @nb_listings;
                push @nb_info, { bairro => $nbname, distancia_km => sprintf('%.2f', $dist) + 0, n_imoveis => scalar(@nb_listings) };
            }
            if (@pool >= 2) {
                $b->{profile_quartos} = mode_of(grep { defined $_ } map { $_->{quartos} } @pool);
                $b->{profile_vagas}   = mode_of(grep { defined $_ } map { $_->{vagas} } @pool);
                $b->{profile_pool_sample_size} = scalar(@pool);
                $b->{profile_reliability} = 'regional';
                $b->{profile_neighbors} = \@nb_info;
            }
        }
    }
}

# ---------------------------------------------------------------------------
# 5c) Mudança 2: Captação Ativa + detecção de lançamento por endereço.
#
# Per address (bairro|rua|número), two independent checks:
#  - coerência de preço: se o menor valor de transação é < R$30.000 ou a razão
#    máx/mín > 20x, o "endereço" quase certamente não é um prédio único de
#    verdade (é um valor símbolo -- partilha, herança -- ou um cadastro
#    genérico da Prefeitura reaproveitado para várias transações distintas).
#    Esses endereços são descartados do painel e não contam para nenhuma
#    métrica de liquidez de revenda.
#  - lançamento: 5+ vendas no mesmo endereço dentro de uma janela de 6 meses
#    (182 dias) em qualquer ponto do período -- assinatura típica de registro
#    em lote de uma incorporadora vendendo/entregando um prédio novo. Uma vez
#    marcado, o endereço inteiro (todas as transações, nos 3 anos) é tratado
#    como não-orgânico.
# ---------------------------------------------------------------------------

my $LAUNCH_MIN_COUNT = 5;
my $LAUNCH_WINDOW_DAYS = 182;
my $ADDR_MIN_VALOR = 30000;
my $ADDR_MAX_RATIO = 20;

sub address_is_price_incoherent {
    my (@valores) = @_;
    return 0 if @valores < 2;
    my @s = sort { $a <=> $b } @valores;
    my ($vmin, $vmax) = ($s[0], $s[-1]);
    return 1 if $vmin < $ADDR_MIN_VALOR;
    return 1 if $vmin > 0 && ($vmax / $vmin) > $ADDR_MAX_RATIO;
    return 0;
}

sub address_is_launch {
    my (@days) = sort { $a <=> $b } @_;
    return 0 if @days < $LAUNCH_MIN_COUNT;
    for my $i (0 .. $#days) {
        my $cnt = 1;
        for my $j ($i + 1 .. $#days) {
            last if $days[$j] - $days[$i] > $LAUNCH_WINDOW_DAYS;
            $cnt++;
        }
        return 1 if $cnt >= $LAUNCH_MIN_COUNT;
    }
    return 0;
}

# liquidez{bairro}{year} = { total => count, revenda => count }
my %liquidez;
for my $b (@TARGETS) { for my $y (2024, 2025, 2026) { $liquidez{$b}{$y} = { total => 0, revenda => 0 }; } }

my @captacao_ativa;
my ($n_addr_total, $n_addr_discarded, $n_addr_launch) = (0, 0, 0);

for my $akey (keys %itbi_addr) {
    my ($bairro, $street, $number) = split(/\|/, $akey, 3);
    my @recs = @{ $itbi_addr{$akey} };

    for my $r (@recs) { $liquidez{$bairro}{ $r->{year} }{total}++; }

    next unless @recs >= 2; # Mudança 2 só olha para endereços com repetição
    $n_addr_total++;

    my @valores = map { $_->{valor} } @recs;
    if (address_is_price_incoherent(@valores)) {
        $n_addr_discarded++;
        next; # não conta nem como revenda nem como lançamento
    }

    my $is_launch = address_is_launch(map { $_->{day} } @recs);
    if ($is_launch) {
        $n_addr_launch++;
        next; # fora da liquidez de revenda
    }

    for my $r (@recs) { $liquidez{$bairro}{ $r->{year} }{revenda}++; }

    # Candidato a Captação Ativa: revenda orgânica com 2+ vendas.
    my @sorted_valores = sort { $a <=> $b } @valores;
    my @areas = sort { $a <=> $b } grep { defined $_ } map { $_->{area} } @recs;
    my $usn_matches = $usn_addr{$akey} // [];
    my @usn_revenda = grep { $_->{situacao} !~ /^(LANCAMENTO|CONSTRUCAO)$/ } @$usn_matches;

    push @captacao_ativa, {
        bairro        => $bairro,
        addr_key      => $akey,
        endereco      => display_street($street) . ', ' . $number,
        n_vendas      => scalar(@recs),
        preco_min     => $sorted_valores[0] + 0,
        preco_max     => $sorted_valores[-1] + 0,
        preco_medio   => sprintf('%.2f', mean(@valores)) + 0,
        area_min      => @areas ? $areas[0] + 0 : undef,
        area_max      => @areas ? $areas[-1] + 0 : undef,
        tem_unidade_a_venda_hoje => (@usn_revenda ? JSON::PP::true : JSON::PP::false),
        unidades_a_venda_hoje => [ map { { codigo => $_->{codigo}, valor => $_->{valor}, link => $_->{link} } } @usn_revenda ],
    };
}

# Liquidez de revenda: também soma automaticamente os endereços com 1 venda
# só (não passam pelo bloco acima porque nunca podem ser lançamento nem
# incoerentes -- uma única transação é, por definição, orgânica). Esses
# mesmos endereços de venda única alimentam a Captação Ativa Estratégica
# (Mudança 12) como fallback quando um bairro tem poucos prédios com giro
# repetido -- "endereço único" ali, menor confiança de giro repetido.
my @captacao_unico;
for my $akey (keys %itbi_addr) {
    my @recs = @{ $itbi_addr{$akey} };
    next unless @recs == 1;
    my ($bairro, $street, $number) = split(/\|/, $akey, 3);
    $liquidez{$bairro}{ $recs[0]{year} }{revenda}++;

    my $usn_matches = $usn_addr{$akey} // [];
    my @usn_revenda = grep { $_->{situacao} !~ /^(LANCAMENTO|CONSTRUCAO)$/ } @$usn_matches;
    push @captacao_unico, {
        bairro        => $bairro,
        addr_key      => $akey,
        endereco      => display_street($street) . ', ' . $number,
        n_vendas      => 1,
        preco_min     => $recs[0]{valor} + 0,
        preco_max     => $recs[0]{valor} + 0,
        preco_medio   => $recs[0]{valor} + 0,
        area_min      => defined $recs[0]{area} ? $recs[0]{area} + 0 : undef,
        area_max      => defined $recs[0]{area} ? $recs[0]{area} + 0 : undef,
        tem_unidade_a_venda_hoje => (@usn_revenda ? JSON::PP::true : JSON::PP::false),
    };
}

@captacao_ativa = sort { $a->{bairro} cmp $b->{bairro} || $b->{n_vendas} <=> $a->{n_vendas} || $a->{addr_key} cmp $b->{addr_key} } @captacao_ativa;

for my $b (@TARGETS) {
    $base{$b}{liquidez_total_2025}   = $liquidez{$b}{2025}{total};
    $base{$b}{liquidez_revenda_2025} = $liquidez{$b}{2025}{revenda};
    $base{$b}{liquidez_por_ano} = {
        map { $_ => { total => $liquidez{$b}{$_}{total}, revenda => $liquidez{$b}{$_}{revenda} } } (2024, 2025, 2026)
    };
}

print STDERR sprintf("Mudanca 2: %d enderecos com 2+ vendas | %d descartados (preco incoerente) | %d marcados como lancamento | %d validos para Captacao Ativa\n",
    $n_addr_total, $n_addr_discarded, $n_addr_launch, scalar(@captacao_ativa));

# ---------------------------------------------------------------------------
# 6) Cross-bairro scoring (Painel 1) + Estoque x Demanda flags (Painel 3)
# ---------------------------------------------------------------------------

my %vol_for_z   = map { $_ => $base{$_}{volume_2025} } @TARGETS;
my %trend_for_z = map { $_ => $base{$_}{trend_pct_for_score} } @TARGETS;
my %vol_z   = zscore_map(%vol_for_z);
my %trend_z = zscore_map(%trend_for_z);

my %combined;
for my $b (@TARGETS) { $combined{$b} = ($vol_z{$b} + $trend_z{$b}) / 2; }
my @cvals = values %combined;
my ($cmin, $cmax) = (percentile(0, @cvals), percentile(100, @cvals));
my $crange = ($cmax - $cmin) || 1;

# Ratio de estoque compativel / demanda, para achar limiar (terco inferior = oportunidade)
my @ratios;
for my $b (@TARGETS) {
    my $d = $base{$b}{volume_2025} || 0;
    my $s = $base{$b}{stock_matching_profile} || 0;
    push @ratios, ($d > 0 ? $s / $d : ($s > 0 ? 999 : 0));
}
my @sorted_ratios = sort { $a <=> $b } @ratios;
my $low_tercile_threshold = $sorted_ratios[ int(@sorted_ratios / 3) ] // 0;

my %final;
for my $b (@TARGETS) {
    my $score = (($combined{$b} - $cmin) / $crange) * 100;
    my $demand = $base{$b}{volume_2025} || 0;
    my $stock_match = $base{$b}{stock_matching_profile} || 0;
    my $ratio = $demand > 0 ? $stock_match / $demand : ($stock_match > 0 ? 999 : 0);

    my $paid = $base{$b}{paid_median_valor_2025};
    my $asking = $base{$b}{asking_median_valor};
    my $price_gap_pct = (defined $paid && defined $asking && $paid > 0) ? (($asking - $paid) / $paid) * 100 : undef;

    my $flag_oportunidade = ($ratio <= $low_tercile_threshold) && $demand > 0;
    my $flag_alerta = defined $price_gap_pct && abs($price_gap_pct) >= 20;

    $final{$b} = {
        %{ $base{$b} },
        score               => sprintf('%.1f', $score) + 0,
        stock_demand_ratio  => sprintf('%.3f', $ratio) + 0,
        price_gap_pct       => defined $price_gap_pct ? sprintf('%.1f', $price_gap_pct) + 0 : undef,
        flag_oportunidade   => $flag_oportunidade ? JSON::PP::true : JSON::PP::false,
        flag_alerta         => $flag_alerta ? JSON::PP::true : JSON::PP::false,
    };
}

# ---------------------------------------------------------------------------
# 6b) Mudança 3, componente (a): score_revenda -- mesma metodologia do score do
# Painel 1 (z-score de volume + z-score de tendência, média, 0-100), mas
# usando liquidez_revenda_2025 no lugar de volume_2025. O Painel 1 continua
# usando "score" (liquidez total), sem alteração.
# ---------------------------------------------------------------------------

my %revenda_for_z = map { $_ => $base{$_}{liquidez_revenda_2025} } @TARGETS;
my %revenda_z = zscore_map(%revenda_for_z);
my %combined_revenda;
for my $b (@TARGETS) { $combined_revenda{$b} = ($revenda_z{$b} + $trend_z{$b}) / 2; }
my @rvals = values %combined_revenda;
my ($rmin, $rmax) = (percentile(0, @rvals), percentile(100, @rvals));
my $rrange = ($rmax - $rmin) || 1;
for my $b (@TARGETS) {
    $final{$b}{score_revenda} = sprintf('%.1f', (($combined_revenda{$b} - $rmin) / $rrange) * 100) + 0;
}

# ---------------------------------------------------------------------------
# 6c) Mudança 3: "Imóveis Prioritários para Campanha" -- pontuação individual
# por anúncio ativo. Ver plano aprovado para a fórmula e os dois ajustes
# (zona de cautela para desconto extremo; amortecimento por confiabilidade
# do Perfil Vencedor da Mudança 1).
# ---------------------------------------------------------------------------

my %in_captacao_ativa = map { $_->{addr_key} => 1 } grep { defined $_->{addr_key} } @captacao_ativa;

sub reliability_confidence {
    my ($rel) = @_;
    return 1.0 if $rel eq 'individual';
    return 0.5 if $rel eq 'regional';
    return 0.0;
}

sub max0 { my ($v) = @_; return $v < 0 ? 0 : $v; }

# Componente (b): alinhamento de preço. Até 30% abaixo da mediana = nota
# máxima (desconto normal de mercado); acima da mediana decai linearmente;
# além de 30% abaixo entra numa zona de cautela onde a nota volta a cair
# (piso 30) em vez de premiar descontos extremos sem limite -- um preço
# longe demais do histórico é mais provável sinal de problema (documentação,
# estado do imóvel, venda urgente) do que uma pechincha genuína.
sub price_alignment_score {
    my ($valor, $mediana) = @_;
    return { score => 50, zone => 'sem_referencia' } unless defined $mediana && $mediana > 0 && defined $valor;
    my $ratio = $valor / $mediana;
    if ($ratio > 1.0) {
        return { score => max0(100 - ($ratio - 1) * 100), ratio => $ratio, zone => 'acima' };
    } elsif ($ratio >= 0.7) {
        return { score => 100, ratio => $ratio, zone => 'normal' };
    } else {
        my $s = 100 - (0.7 - $ratio) * 200;
        return { score => ($s < 30 ? 30 : $s), ratio => $ratio, zone => 'cautela' };
    }
}

my @imoveis_prioritarios;
for my $bairro (@TARGETS) {
    my $x = $final{$bairro};
    my $listings = $usn{$bairro} // [];
    my $area_conf    = reliability_confidence($x->{area_band_reliability});
    my $profile_conf = reliability_confidence($x->{profile_reliability});
    my ($lo, $hi) = $x->{area_band} ? @{ $x->{area_band} } : (undef, undef);

    for my $u (@$listings) {
        next unless defined $u->{valor} && $u->{valor} > 0;

        my $pa = price_alignment_score($u->{valor}, $x->{paid_median_valor_2025});

        # Componente (c), sub-nota metragem: dentro da faixa vencedora = 100;
        # fora, decai com a distância relativa à largura da própria faixa.
        my $area_raw = 50;
        if (defined $lo && defined $u->{area}) {
            if ($u->{area} >= $lo && $u->{area} < $hi) { $area_raw = 100; }
            else {
                my $band_width = $hi - $lo;
                my $dist = $u->{area} < $lo ? $lo - $u->{area} : $u->{area} - $hi;
                $area_raw = max0(100 - ($dist / $band_width) * 100);
            }
        }
        my $area_score = 50 + ($area_raw - 50) * $area_conf;

        my $quartos_raw = 50;
        if (defined $x->{profile_quartos} && defined $u->{quartos}) {
            my $diff = abs($u->{quartos} - $x->{profile_quartos});
            $quartos_raw = $diff == 0 ? 100 : ($diff == 1 ? 50 : 0);
        }
        my $quartos_score = 50 + ($quartos_raw - 50) * $profile_conf;

        my $vagas_raw = 50;
        if (defined $x->{profile_vagas} && defined $u->{vagas}) {
            my $diff = abs($u->{vagas} - $x->{profile_vagas});
            $vagas_raw = $diff == 0 ? 100 : ($diff == 1 ? 50 : 0);
        }
        my $vagas_score = 50 + ($vagas_raw - 50) * $profile_conf;

        my $aderencia = mean($area_score, $quartos_score, $vagas_score);

        my $tem_captacao = defined($u->{addr_key}) && exists $in_captacao_ativa{ $u->{addr_key} };

        my $final_score = 0.35 * $x->{score_revenda}
                        + 0.30 * $pa->{score}
                        + 0.25 * $aderencia
                        + 0.10 * ($tem_captacao ? 100 : 0);

        # Resumo curto: as 2-3 frases mais fortes, priorizando alertas de preço.
        my @frases;
        if ($pa->{zone} eq 'cautela') {
            push @frases, sprintf('Preço %.0f%% abaixo do histórico do bairro — vale checar antes de anunciar', (1 - $pa->{ratio}) * 100);
        } elsif ($pa->{zone} eq 'acima' && $pa->{score} < 60) {
            push @frases, sprintf('Preço %.0f%% acima do que o bairro historicamente pagou', ($pa->{ratio} - 1) * 100);
        } elsif ($pa->{zone} eq 'normal' && defined $pa->{ratio} && $pa->{ratio} < 0.97) {
            push @frases, sprintf('Preço %.0f%% abaixo da mediana paga no bairro', (1 - $pa->{ratio}) * 100);
        }
        if ($aderencia >= 80) {
            push @frases, 'Bate com o perfil vencedor do bairro' . ($profile_conf < 1 ? ' (estimativa regional)' : '');
        }
        if ($x->{score_revenda} >= 70) {
            push @frases, 'Bairro com liquidez de revenda alta';
        }
        push @frases, 'Prédio com histórico de giro comprovado' if $tem_captacao;
        @frases = @frases[0..1] if @frases > 2;

        push @imoveis_prioritarios, {
            bairro       => $bairro,
            endereco     => $u->{endereco},
            codigo       => $u->{codigo},
            link         => $u->{link},
            valor        => $u->{valor},
            area         => $u->{area},
            quartos      => $u->{quartos},
            vagas        => $u->{vagas},
            score_bairro_revenda => sprintf('%.1f', $x->{score_revenda}) + 0,
            price_alignment      => sprintf('%.1f', $pa->{score}) + 0,
            profile_adherence    => sprintf('%.1f', $aderencia) + 0,
            tem_captacao_ativa   => $tem_captacao ? JSON::PP::true : JSON::PP::false,
            area_band_reliability => $x->{area_band_reliability},
            profile_reliability   => $x->{profile_reliability},
            final_score  => sprintf('%.1f', $final_score) + 0,
            resumo       => join(' · ', @frases),
        };
    }
}
@imoveis_prioritarios = sort { $b->{final_score} <=> $a->{final_score} } @imoveis_prioritarios;

print STDERR sprintf("Mudanca 3: %d imoveis pontuados (score medio=%.1f, top score=%.1f)\n",
    scalar(@imoveis_prioritarios),
    (mean(map { $_->{final_score} } @imoveis_prioritarios) // 0),
    ($imoveis_prioritarios[0] ? $imoveis_prioritarios[0]{final_score} : 0));

# ---------------------------------------------------------------------------
# 6d) Mudança 5: "Valor de Oportunidade" -- imóveis anunciados 20%+ abaixo da
# mediana paga em 2025 no bairro. Bairros com menos de 10 vendas em 2025 ficam
# de fora (mediana calculada com poucos pontos não é confiável o suficiente
# pra virar "achado"). Descontos acima de 30% (mesmo limiar da zona de cautela
# da Mudança 3) ganham um aviso extra em vez de sumir da lista.
# ---------------------------------------------------------------------------

my $VALOR_OPORTUNIDADE_MIN_DESCONTO = 0.20; # 20%+
my $VALOR_OPORTUNIDADE_ATENCAO_DESCONTO = 0.30; # mesmo limiar da "zona de cautela" (Mudança 3)
my $VALOR_OPORTUNIDADE_MIN_VENDAS_2025 = 10;

my @valor_oportunidade_imoveis;
for my $r (@imoveis_prioritarios) {
    my $bx = $final{ $r->{bairro} };
    next unless ($bx->{yearly}{2025}{count} // 0) >= $VALOR_OPORTUNIDADE_MIN_VENDAS_2025;
    my $mediana = $bx->{paid_median_valor_2025};
    next unless defined $mediana && $mediana > 0;
    my $ratio = $r->{valor} / $mediana;
    my $desconto = 1 - $ratio;
    next unless $desconto >= $VALOR_OPORTUNIDADE_MIN_DESCONTO;

    push @valor_oportunidade_imoveis, {
        bairro       => $r->{bairro},
        endereco     => $r->{endereco},
        codigo       => $r->{codigo},
        link         => $r->{link},
        valor        => $r->{valor},
        mediana_paga_bairro => $mediana,
        desconto_pct => sprintf('%.1f', $desconto * 100) + 0,
        atencao      => ($desconto >= $VALOR_OPORTUNIDADE_ATENCAO_DESCONTO) ? JSON::PP::true : JSON::PP::false,
    };
}
@valor_oportunidade_imoveis = sort { $b->{desconto_pct} <=> $a->{desconto_pct} } @valor_oportunidade_imoveis;

my %achados_by_bairro;
my %stock_by_bairro_elegivel;
for my $r (@imoveis_prioritarios) {
    my $bx = $final{ $r->{bairro} };
    next unless ($bx->{yearly}{2025}{count} // 0) >= $VALOR_OPORTUNIDADE_MIN_VENDAS_2025;
    $stock_by_bairro_elegivel{ $r->{bairro} }++;
}
$achados_by_bairro{ $_->{bairro} }++ for @valor_oportunidade_imoveis;

my @valor_oportunidade_por_bairro;
for my $b (keys %stock_by_bairro_elegivel) {
    my $n = $achados_by_bairro{$b} // 0;
    next unless $n > 0;
    push @valor_oportunidade_por_bairro, {
        bairro        => $b,
        n_achados     => $n,
        estoque_total => $stock_by_bairro_elegivel{$b},
        pct_do_estoque => sprintf('%.1f', 100 * $n / $stock_by_bairro_elegivel{$b}) + 0,
    };
}
@valor_oportunidade_por_bairro = sort { $b->{n_achados} <=> $a->{n_achados} || $a->{bairro} cmp $b->{bairro} } @valor_oportunidade_por_bairro;

my $n_excluidos_por_volume = grep { ($final{$_}{yearly}{2025}{count} // 0) < $VALOR_OPORTUNIDADE_MIN_VENDAS_2025 } @TARGETS;
print STDERR sprintf("Mudanca 5: %d achados (>=20%% desconto) em %d bairros com achados; %d bairros excluidos por menos de %d vendas em 2025\n",
    scalar(@valor_oportunidade_imoveis), scalar(@valor_oportunidade_por_bairro),
    $n_excluidos_por_volume, $VALOR_OPORTUNIDADE_MIN_VENDAS_2025);

# ---------------------------------------------------------------------------
# 6e) "Prontidão para Campanha por Bairro" -- combina 6 sinais já calculados
# (liquidez/tendência do Painel 1, estoque compatível do Painel 3, alinhamento
# de preço do Painel 4, captação ativa do Painel 6, imóveis prioritários do
# Painel 7, concentração de achados de valor do Painel 9) num único score de
# "esse bairro tem munição real pra campanha agora?", distinto da pergunta de
# liquidez pura do Painel 1. Pesos e normalização aprovados pelo usuário:
#   0,15*liquidez + 0,20*estoque + 0,15*preço + 0,15*captação + 0,25*imóveis + 0,10*valor
# Dado faltante vira nota neutra (50), nunca 0 -- mesma regra de não penalizar
# por gap de dado usada desde a Mudança 1. As duas exceções onde 0 é o valor
# correto (porque é um resultado real, não uma ausência de dado): zero imóveis
# pontuados no bairro, e zero achados de valor num bairro com estoque elegível
# suficiente pra avaliar.
# ---------------------------------------------------------------------------

my %captacao_count_by_bairro;
$captacao_count_by_bairro{ $_->{bairro} }++ for @captacao_ativa;

my %f2_raw = map { $_ => $final{$_}{stock_matching_profile} || 0 } @TARGETS;
my %f4_raw = map { $_ => $captacao_count_by_bairro{$_} || 0 } @TARGETS;
my %f2 = normalize_0_100(%f2_raw);
my %f4 = normalize_0_100(%f4_raw);

my %imoveis_by_bairro;
for my $r (@imoveis_prioritarios) { push @{ $imoveis_by_bairro{ $r->{bairro} } }, $r; } # já vem ordenado desc

for my $b (@TARGETS) {
    my $x = $final{$b};
    my $f1 = $x->{score};
    my $f2v = $f2{$b};

    my $gap = $x->{price_gap_pct};
    my $f3 = defined $gap ? max0(100 - abs($gap) * 2) : 50; # decai a 0 num gap de +-50%; sem dado -> neutro

    my $f4v = $f4{$b};

    my $list = $imoveis_by_bairro{$b} // [];
    my $n = scalar(@$list);
    my $top_n = $n < 10 ? $n : 10;
    my @top10 = $n ? @{$list}[0 .. $top_n-1] : ();
    my $mean_top10 = $n ? mean(map { $_->{final_score} } @top10) : 0;
    my $coverage = $n / 10; $coverage = 1 if $coverage > 1;
    my $f5 = $mean_top10 * $coverage;

    my $vendas_2025 = $x->{yearly}{2025}{count} // 0;
    my $f6;
    if ($vendas_2025 < $VALOR_OPORTUNIDADE_MIN_VENDAS_2025) {
        $f6 = 50; # dado insuficiente pra medir concentração de achados -> neutro
    } else {
        my $estoque_eleg = $stock_by_bairro_elegivel{$b} // 0;
        $f6 = $estoque_eleg == 0 ? 0 : 100 * ($achados_by_bairro{$b} // 0) / $estoque_eleg;
    }

    $final{$b}{prontidao_campanha} = sprintf('%.1f',
        0.15*$f1 + 0.20*$f2v + 0.15*$f3 + 0.15*$f4v + 0.25*$f5 + 0.10*$f6) + 0;
}

my @prontidao_ranking = sort { $final{$b}{prontidao_campanha} <=> $final{$a}{prontidao_campanha} } @TARGETS;

print STDERR sprintf("Mudanca 10: prontidao de campanha calculada para %d bairros (topo: %s=%.1f)\n",
    scalar(@TARGETS), $prontidao_ranking[0], $final{$prontidao_ranking[0]}{prontidao_campanha});

# ---------------------------------------------------------------------------
# 7) Mudança 11: bairros em escassez macro de estoque ("Prioridade Máxima" na
# Captação Ativa Estratégica, Mudança 12) + Índice de Saturação de Oferta
# (badge nos Painéis 1 e 2)
# ---------------------------------------------------------------------------

# Escassez macro de bairro -- demanda comprovada (mesmo piso de
# confiabilidade estatística já usado no Painel 10, $VALOR_OPORTUNIDADE_MIN_VENDAS_2025
# vendas em 2025) cruzada com quase nada no perfil vencedor à venda hoje.
# Diferente do critério de ENDEREÇO da Captação Ativa Estratégica (histórico
# de giro de um prédio específico, em qualquer bairro): aqui a escassez é do
# bairro inteiro, e vira a badge "Prioridade Máxima" -- o bairro sobe pro
# topo da lista, mas nunca decide sozinho quem aparece nela.
my $CAPTACAO_ESTRATEGICA_MAX_STOCK_MATCH = 2; # 0-2 imóveis no perfil vencedor = escassez de bairro

for my $b (@TARGETS) {
    my $vol = $final{$b}{volume_2025} || 0;
    my $smp = $final{$b}{stock_matching_profile} || 0;
    $final{$b}{flag_prioridade_maxima} = ($smp <= $CAPTACAO_ESTRATEGICA_MAX_STOCK_MATCH && $vol >= $VALOR_OPORTUNIDADE_MIN_VENDAS_2025)
        ? JSON::PP::true : JSON::PP::false;
}

print STDERR sprintf("Mudanca 11: %d bairros em escassez macro (Prioridade Maxima: estoque no perfil <= %d, volume_2025 >= %d)\n",
    scalar(grep { $final{$_}{flag_prioridade_maxima} } @TARGETS), $CAPTACAO_ESTRATEGICA_MAX_STOCK_MATCH, $VALOR_OPORTUNIDADE_MIN_VENDAS_2025);

# Índice de Saturação de Oferta -- o oposto do flag_oportunidade (Painel 3),
# que usa stock_matching_profile no numerador. Aqui o numerador é o ESTOQUE
# TOTAL do bairro (todos os anúncios ativos, não só os que batem o perfil
# vencedor), porque a pergunta é "tem anúncio demais disputando essa
# demanda" (mercado concorrido, leads mais frios/caros), não "tem o imóvel
# certo à venda" -- as duas coisas podem, inclusive, ser verdade ao mesmo
# tempo no mesmo bairro (estoque geral inchado, mas quase nada no que
# realmente vende). Mesma técnica de tercil já usada para o
# flag_oportunidade, mas no terço SUPERIOR da razão em vez do inferior.
my @stotal_ratios;
for my $b (@TARGETS) {
    my $d = $final{$b}{volume_2025} || 0;
    my $s = $final{$b}{stock_total} || 0;
    push @stotal_ratios, ($d > 0 ? $s / $d : ($s > 0 ? 999 : 0));
}
my @sorted_stotal_ratios = sort { $a <=> $b } @stotal_ratios;
my $high_tercile_threshold = $sorted_stotal_ratios[ int(2 * @sorted_stotal_ratios / 3) ] // 0;

for my $b (@TARGETS) {
    my $d = $final{$b}{volume_2025} || 0;
    my $s = $final{$b}{stock_total} || 0;
    my $ratio = $d > 0 ? $s / $d : ($s > 0 ? 999 : 0);
    $final{$b}{stock_total_demand_ratio} = sprintf('%.3f', $ratio) + 0;
    $final{$b}{flag_saturacao_alta} = ($ratio >= $high_tercile_threshold) ? JSON::PP::true : JSON::PP::false;
}

print STDERR sprintf("Mudanca 11: %d bairros marcados Saturacao Alta (limiar estoque_total/demanda >= %.3f)\n",
    scalar(grep { $final{$_}{flag_saturacao_alta} } @TARGETS), $high_tercile_threshold);

# ---------------------------------------------------------------------------
# 8) Mudança 12: Captação Ativa Estratégica (fusão dos antigos Painel 7 +
# Painel 11) -- lista de PRÉDIOS pra prospecção ativa, agrupada por bairro.
#
# Critério de ENDEREÇO (decide QUEM APARECE, em qualquer um dos 47 bairros):
# mesmo critério do antigo Painel 7 (2+ vendas de revenda orgânica, exclui
# lançamento e preço incoerente) + SEM unidade à venda hoje na Usenonstop --
# se já tem anúncio ativo, não precisa prospecção, é só contatar pelo
# anúncio. Quando um bairro tem menos de 5 endereços assim, relaxa incluindo
# TODOS os endereços com 1 venda só disponíveis (marcados "endereço único",
# menor confiança de giro repetido) -- sem isso, bairros finos em prédios de
# giro repetido ficariam sem material nenhum pra prospecção.
#
# Critério de BAIRRO (decide QUEM SOBE PRO TOPO, nunca quem aparece):
# bairros com flag_prioridade_maxima (Mudança 11, escassez de estoque no
# nível do bairro inteiro) recebem a badge "Prioridade Máxima" e vêm
# primeiro na lista.
# ---------------------------------------------------------------------------

my $CAPTACAO_ESTRATEGICA_MIN_ENDERECOS = 5;

my %estrategica_by_bairro;
for my $c (@captacao_ativa) {
    next if $c->{tem_unidade_a_venda_hoje};
    push @{ $estrategica_by_bairro{ $c->{bairro} } }, {
        endereco  => $c->{endereco},
        n_vendas  => $c->{n_vendas},
        preco_min => $c->{preco_min},
        preco_max => $c->{preco_max},
        area_min  => $c->{area_min},
        area_max  => $c->{area_max},
        unico     => JSON::PP::false,
    };
}
for my $bairro (@TARGETS) {
    my $n = scalar(@{ $estrategica_by_bairro{$bairro} // [] });
    next if $n >= $CAPTACAO_ESTRATEGICA_MIN_ENDERECOS;
    for my $c (grep { $_->{bairro} eq $bairro && !$_->{tem_unidade_a_venda_hoje} } @captacao_unico) {
        push @{ $estrategica_by_bairro{$bairro} }, {
            endereco  => $c->{endereco},
            n_vendas  => $c->{n_vendas},
            preco_min => $c->{preco_min},
            preco_max => $c->{preco_max},
            area_min  => $c->{area_min},
            area_max  => $c->{area_max},
            unico     => JSON::PP::true,
        };
    }
}

my @captacao_estrategica;
for my $bairro (@TARGETS) {
    my @enderecos = @{ $estrategica_by_bairro{$bairro} // [] };
    next unless @enderecos;
    @enderecos = sort { $b->{n_vendas} <=> $a->{n_vendas} || $a->{endereco} cmp $b->{endereco} } @enderecos;
    push @captacao_estrategica, {
        bairro                 => $bairro,
        flag_prioridade_maxima => $final{$bairro}{flag_prioridade_maxima},
        perfil => {
            area_band           => $final{$bairro}{area_band},
            price_band          => $final{$bairro}{price_band},
            profile_quartos     => $final{$bairro}{profile_quartos},
            profile_vagas       => $final{$bairro}{profile_vagas},
            profile_reliability => $final{$bairro}{profile_reliability},
        },
        enderecos => \@enderecos,
    };
}
@captacao_estrategica = sort {
    ($b->{flag_prioridade_maxima} ? 1 : 0) <=> ($a->{flag_prioridade_maxima} ? 1 : 0)
        || $final{ $b->{bairro} }{volume_2025} <=> $final{ $a->{bairro} }{volume_2025}
        || $a->{bairro} cmp $b->{bairro}
} @captacao_estrategica;

print STDERR sprintf("Mudanca 12: %d bairros na Captacao Ativa Estrategica (%d com Prioridade Maxima), %d enderecos no total\n",
    scalar(@captacao_estrategica),
    scalar(grep { $_->{flag_prioridade_maxima} } @captacao_estrategica),
    eval { my $t = 0; $t += scalar(@{$_->{enderecos}}) for @captacao_estrategica; $t });

# ---------------------------------------------------------------------------
# 9) Write JSON
# ---------------------------------------------------------------------------

my @ranked = sort { $final{$b}{score} <=> $final{$a}{score} } @TARGETS;
my $output = {
    generated_at => scalar(gmtime()) . ' UTC',
    meta => {
        total_itbi_rows_seen    => $total_rows_seen,
        total_itbi_rows_matched => $total_rows_matched,
        usn_rows_seen           => $usn_rows_seen,
        usn_rows_matched        => $usn_rows_matched,
        area_bucket_width       => $AREA_BUCKET_WIDTH,
        enderecos_com_repeticao      => $n_addr_total,
        enderecos_descartados_preco  => $n_addr_discarded,
        enderecos_lancamento         => $n_addr_launch,
        enderecos_captacao_ativa     => scalar(@captacao_ativa),
        fontes_descoberta       => {
            itbi_meses => scalar(grep { 1 } map { keys %{ $itbi_periods->{$_} } } keys %$itbi_periods),
            usenonstop_arquivo => $usn_source->{display},
        },
        avisos_descoberta => \@discovery_warnings,
    },
    ranking  => \@ranked,
    prontidao_ranking => \@prontidao_ranking,
    bairros  => \%final,
    captacao_ativa => \@captacao_ativa,
    imoveis_prioritarios => \@imoveis_prioritarios,
    valor_oportunidade => {
        imoveis   => \@valor_oportunidade_imoveis,
        por_bairro => \@valor_oportunidade_por_bairro,
    },
    captacao_estrategica => \@captacao_estrategica,
};

open(my $out, '>:encoding(UTF-8)', $OUT_FILE) or die "cannot write $OUT_FILE: $!";
print $out JSON::PP->new->utf8(0)->canonical->pretty->encode($output);
close $out;

print STDERR "OK: dados escritos em $OUT_FILE\n";

# ---------------------------------------------------------------------------
# Mudança 8: write the raw-record payload embedded into dashboard.html for
# client-side filtering. Kept in a separate file from $OUT_FILE (the
# aggregate) so atualizar.sh's week-over-week diff and this export don't have
# to agree on one shape, and so dashboard.html doesn't embed both.
# ---------------------------------------------------------------------------

my $raw_output = {
    generated_at => scalar(gmtime()) . ' UTC',
    total_itbi_rows_seen => $total_rows_seen,
    avisos_descoberta => \@discovery_warnings,
    bairros => \@TARGETS,
    addr_display => \@addr_display,
    itbi => \@itbi_raw,
    usenonstop => \@usn_raw,
    constants => {
        area_cap => $AREA_CAP,
        area_bucket_width => $AREA_BUCKET_WIDTH,
        max_per_exact_area => $MAX_PER_EXACT_AREA,
        reliability_threshold => $RELIABILITY_THRESHOLD,
        neighbor_max_km => $NEIGHBOR_MAX_KM,
        neighbor_count => $NEIGHBOR_COUNT,
        trend_cap => $TREND_CAP,
        launch_min_count => $LAUNCH_MIN_COUNT,
        launch_window_days => $LAUNCH_WINDOW_DAYS,
        addr_min_valor => $ADDR_MIN_VALOR,
        addr_max_ratio => $ADDR_MAX_RATIO,
        valor_oportunidade_min_desconto => $VALOR_OPORTUNIDADE_MIN_DESCONTO,
        valor_oportunidade_atencao_desconto => $VALOR_OPORTUNIDADE_ATENCAO_DESCONTO,
        valor_oportunidade_min_vendas_2025 => $VALOR_OPORTUNIDADE_MIN_VENDAS_2025,
        captacao_estrategica_max_stock_match => $CAPTACAO_ESTRATEGICA_MAX_STOCK_MATCH,
        captacao_estrategica_min_enderecos => $CAPTACAO_ESTRATEGICA_MIN_ENDERECOS,
        excel_epoch_unix => $EXCEL_EPOCH,
    },
};

my $RAW_OUT_FILE = "$ROOT/data/dashboard_raw.json";
open(my $rawfh, '>:encoding(UTF-8)', $RAW_OUT_FILE) or die "cannot write $RAW_OUT_FILE: $!";
print $rawfh JSON::PP->new->utf8(0)->canonical->encode($raw_output);
close $rawfh;
print STDERR sprintf("OK: dados brutos escritos em %s (%d transacoes, %d anuncios, %d enderecos)\n",
    $RAW_OUT_FILE, scalar(@itbi_raw), scalar(@usn_raw), scalar(@addr_display));
