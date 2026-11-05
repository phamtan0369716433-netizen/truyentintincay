#!/bin/bash

compare() {
  if diff -q $1 $2 > /dev/null; then
    printf "\nSUCCESS: Message received matches message sent!\n\n"
  else
    printf "\nFAILURE: Message received doesn't match message sent.\n\n"
  fi
}

compare $1 $2
