#!/usr/bin/perl
# Embeds data/dashboard_raw.json (the raw-record payload) into
# dashboard_template.html, producing ../dashboard.html. Shared by build.sh and
# atualizar.sh so there is a single place that knows how the template
# placeholder works. dashboard_data.json (the pre-computed aggregate) is NOT
# embedded — it exists only for atualizar.sh's week-over-week diff and as a
# verification reference for the client-side engine (see verify_raw.pl).
use strict;
use warnings;
use utf8;
use FindBin qw($Bin);

local $/;
open(my $tf, '<:encoding(UTF-8)', "$Bin/dashboard_template.html") or die $!;
my $template = <$tf>;
close $tf;
open(my $df, '<:encoding(UTF-8)', "$Bin/../data/dashboard_raw.json") or die $!;
my $json = <$df>;
close $df;
my $marker = '__DASHBOARD_RAW_JSON__';
my $pos = index($template, $marker);
die "marker not found in template" if $pos < 0;
substr($template, $pos, length($marker)) = $json;
open(my $of, '>:encoding(UTF-8)', "$Bin/../dashboard.html") or die $!;
print $of $template;
close $of;
print STDERR "OK: dashboard.html gerado.\n";
