#!/usr/bin/perl
# Compares the JavaScript engine's unfiltered output (computeAll with no
# bairro/price filter) against the Perl-computed aggregate in
# data/dashboard_data.json, field by field. Used once during the Mudança 9
# implementation to prove the JS port didn't diverge from build_data.pl's
# methodology; safe to re-run any time the engine changes on either side.
#
# Usage: perl verify_raw.pl <js_result.json> <perl_dashboard_data.json>
use strict;
use warnings;
use utf8;
use JSON::PP;

binmode(STDOUT, ':encoding(UTF-8)');
binmode(STDERR, ':encoding(UTF-8)');

my ($js_path, $perl_path) = @ARGV;
die "uso: verify_raw.pl <js_result.json> <perl_dashboard_data.json>\n" unless $js_path && $perl_path;

sub load { my ($p) = @_; open(my $fh,'<:encoding(UTF-8)',$p) or die $!; local $/; my $c=<$fh>; close $fh; return JSON::PP->new->decode($c); }

my $js = load($js_path);
my $pl = load($perl_path);

my $diffs = 0;
sub near {
    my ($a, $b, $tol) = @_;
    $tol //= 0.05;
    return 1 if !defined($a) && !defined($b);
    return 0 if !defined($a) || !defined($b);
    return abs($a-$b) <= $tol;
}
sub report { my ($ctx) = @_; $diffs++; print "DIFF: $ctx\n"; }

# --- ranking order ---
my @jr = @{$js->{ranking}};
my @pr = @{$pl->{ranking}};
if (scalar(@jr) != scalar(@pr)) { report("ranking length: js=".scalar(@jr)." perl=".scalar(@pr)); }
for my $i (0..$#pr) {
    if (($jr[$i]//'') ne ($pr[$i]//'')) {
        report(sprintf("ranking[%d]: js=%s perl=%s", $i, $jr[$i]//'undef', $pr[$i]//'undef'));
    }
}

# --- prontidao_ranking order ---
my @jpr = @{$js->{prontidao_ranking}};
my @ppr = @{$pl->{prontidao_ranking}};
if (scalar(@jpr) != scalar(@ppr)) { report("prontidao_ranking length: js=".scalar(@jpr)." perl=".scalar(@ppr)); }
for my $i (0..$#ppr) {
    if (($jpr[$i]//'') ne ($ppr[$i]//'')) {
        report(sprintf("prontidao_ranking[%d]: js=%s perl=%s", $i, $jpr[$i]//'undef', $ppr[$i]//'undef'));
    }
}

# --- per-bairro fields ---
my @fields_exact = qw(volume_2025 profile_quartos profile_vagas profile_sample_size
    stock_total stock_matching_profile area_band_reliability profile_reliability
    liquidez_total_2025 liquidez_revenda_2025 flag_oportunidade flag_alerta);
my @fields_numeric = qw(score score_revenda stock_demand_ratio price_gap_pct
    paid_median_valor_2025 asking_median_valor prontidao_campanha);

for my $b (sort keys %{$pl->{bairros}}) {
    my $jx = $js->{bairros}{$b};
    my $px = $pl->{bairros}{$b};
    unless ($jx) { report("bairro '$b' ausente no resultado JS"); next; }

    for my $f (@fields_exact) {
        my ($jv, $pv) = ($jx->{$f}, $px->{$f});
        $jv = $jv ? 1 : 0 if JSON::PP::is_bool($jv);
        $pv = $pv ? 1 : 0 if JSON::PP::is_bool($pv);
        no warnings 'uninitialized';
        if (("$jv" ne "$pv")) { report("$b.$f: js=".(defined $jv?$jv:'undef')." perl=".(defined $pv?$pv:'undef')); }
    }
    for my $f (@fields_numeric) {
        unless (near($jx->{$f}, $px->{$f}, 0.15)) {
            report("$b.$f: js=".(defined $jx->{$f}?$jx->{$f}:'undef')." perl=".(defined $px->{$f}?$px->{$f}:'undef'));
        }
    }
    for my $f (qw(area_band price_band)) {
        my ($ja, $pa) = ($jx->{$f}, $px->{$f});
        if ((defined $ja) != (defined $pa)) { report("$b.$f: definedness differs (js=".(defined $ja?'yes':'no').", perl=".(defined $pa?'yes':'no').")"); }
        elsif (defined $ja) {
            report("$b.$f\[0\]: js=$ja->[0] perl=$pa->[0]") unless near($ja->[0], $pa->[0], 0.5);
            report("$b.$f\[1\]: js=$ja->[1] perl=$pa->[1]") unless near($ja->[1], $pa->[1], 0.5);
        }
    }
}

# --- captacao_ativa: same set of addresses with same counts ---
# Key is accent/case-normalized: the new addr_display dictionary (Mudança 9)
# prefers Usenonstop's natural casing/accents when available, while the older
# Perl captacao_ativa builder (Mudança 2, untouched) always derives from the
# plain uppercase ITBI street name -- same address, cosmetically different
# text, not a methodology divergence. Every field *other than the string
# itself* is still compared below.
sub norm_key {
    my ($s) = @_;
    $s = uc($s);
    my %map = ('Á'=>'A','À'=>'A','Ã'=>'A','Â'=>'A','É'=>'E','Ê'=>'E','Í'=>'I','Ó'=>'O','Õ'=>'O','Ô'=>'O','Ú'=>'U','Ç'=>'C');
    for my $k (keys %map) { $s =~ s/\Q$k\E/$map{$k}/g; }
    $s =~ s/[^A-Z0-9|]//g; # ignore punctuation/hyphen formatting differences too
    return $s;
}
my %js_capt = map { norm_key($_->{bairro}.'|'.$_->{endereco}) => $_ } @{$js->{captacao_ativa}};
my %pl_capt = map { norm_key($_->{bairro}.'|'.$_->{endereco}) => $_ } @{$pl->{captacao_ativa}};
printf("captacao_ativa: js=%d perl=%d entries\n", scalar(@{$js->{captacao_ativa}}), scalar(@{$pl->{captacao_ativa}}));
for my $k (keys %pl_capt) {
    unless (exists $js_capt{$k}) { report("captacao_ativa missing in JS: $k"); next; }
    my ($j,$p) = ($js_capt{$k}, $pl_capt{$k});
    report("captacao($k).n_vendas: js=$j->{n_vendas} perl=$p->{n_vendas}") if $j->{n_vendas} != $p->{n_vendas};
}
for my $k (keys %js_capt) {
    report("captacao_ativa extra in JS (not in Perl): $k") unless exists $pl_capt{$k};
}

# --- imoveis_prioritarios: same set, same scores (order can wobble on exact ties only) ---
my @jip = @{$js->{imoveis_prioritarios}};
my @pip = @{$pl->{imoveis_prioritarios}};
printf("imoveis_prioritarios: js=%d perl=%d entries\n", scalar(@jip), scalar(@pip));
my %pip_by_key = map { ($_->{codigo}//'').'|'.$_->{bairro} => $_ } @pip;
my $score_mismatches = 0;
for my $j (@jip) {
    my $k = ($j->{codigo}//'').'|'.$j->{bairro};
    my $p = $pip_by_key{$k};
    unless ($p) { report("imovel ausente no perl: $k"); next; }
    $score_mismatches++ unless near($j->{final_score}, $p->{final_score}, 0.15);
}
report("imoveis_prioritarios: $score_mismatches score mismatches") if $score_mismatches;

# order check (top 20 only, since exact-tie ordering among equal scores is not
# guaranteed identical -- see notes in dashboard_template.html)
for my $i (0..19) {
    last unless $pip[$i];
    my ($jc, $pc) = ($jip[$i]{codigo}//'', $pip[$i]{codigo}//'');
    report(sprintf("imoveis_prioritarios order[%d]: js=%s perl=%s", $i, $jc, $pc)) if $jc ne $pc;
}

if ($diffs == 0) {
    print "\n=== OK: nenhuma divergencia encontrada. Motor em JS reproduz o resultado do Perl. ===\n";
} else {
    print "\n=== $diffs divergencia(s) encontrada(s). ===\n";
}
