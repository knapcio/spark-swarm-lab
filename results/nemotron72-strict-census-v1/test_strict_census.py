import unittest
import strict_census as c

class StrictCensusTests(unittest.TestCase):
    def solved(self,text,numbers,target):return any(b['solved']for b in c.extract(text,numbers,target))
    def test_exact_multistep_with_spans(self):
        text='Reasoning α\nMove 1: 3 + 4 = 7\nMove 2: 7 * 2 = 14\nDone.'
        b=c.extract(text,[3,4,2],14)[0]
        self.assertTrue(b['solved']);self.assertEqual(text[b['start_character']:b['end_character']],b['text'])
        self.assertEqual(b['start_character'],text.index('Move'));self.assertEqual(b['steps'][1]['action'],{'i':1,'j':0,'op':'*'})
    def test_available_duplicate_is_consumed_twice(self):self.assertTrue(self.solved('Step 1: 3 + 3 = 6',[3,3],6))
    def test_duplicate_single_instance_rejected(self):self.assertFalse(self.solved('Step 1: 3 + 3 = 6',[3,8],6))
    def test_consumed_operand_cannot_be_reused(self):self.assertFalse(self.solved('Step 1: 3 + 4 = 7\nStep 2: 3 + 7 = 10',[3,4,2],10))
    def test_noncommutative_operands_never_swapped(self):self.assertFalse(self.solved('Move 1: 2 - 9 = 7',[2,9],7))
    def test_false_equation_rejected(self):self.assertFalse(self.solved('Move 1: 3 + 4 = 8',[3,4],8))
    def test_negative_result_rejected(self):self.assertFalse(self.solved('Move 1: 3 - 4 = -1',[3,4],-1))
    def test_fraction_intermediate_rejected(self):self.assertFalse(self.solved('Move 1: 3 / 4 = 3/4',[3,4],Fraction(3,4)))
    def test_zero_result_rejected(self):self.assertFalse(self.solved('Move 1: 3 - 3 = 0',[3,3],0))
    def test_zero_division_rejected(self):self.assertFalse(self.solved('Move 1: 3 / 0 = 3',[3,0],3))
    def test_chain_is_unsupported_not_simplified(self):self.assertEqual(c.extract('Move 1: 3 + 4 = 7 * 2 = 14',[3,4,2],14)[0]['status'],'unsupported_format')
    def test_numbering_gap_rejected(self):self.assertFalse(self.solved('Step 1: 3 + 4 = 7\nStep 3: 7 * 2 = 14',[3,4,2],14))
    def test_steps_not_reordered(self):self.assertFalse(self.solved('Step 2: 3 + 4 = 7\nStep 1: 7 * 2 = 14',[3,4,2],14))
    def test_bad_step_not_skipped(self):self.assertFalse(self.solved('Step 1: 3 + 4 = 8\nStep 2: 3 + 4 = 7',[3,4,2],7))
    def test_later_bad_equation_rejects_even_successful_prefix(self):self.assertFalse(self.solved('Step 1: 3 + 4 = 7\nStep 2: 7 + 2 = 10',[3,4,2],7))
    def test_unsupported_numbered_line_not_skipped(self):self.assertEqual(c.extract('Step 1: 3 + 4 = 7\nStep 2 -> do something',[3,4,2],7)[0]['status'],'unsupported_format')
    def test_isolated_and_hypothetical_equations_not_detected(self):
        for text in ['3 + 4 = 7','If we had 3, then 3 + 4 = 7','Hypothetical Step 1: 3 + 4 = 7']:
            self.assertEqual(c.extract(text,[3,4],7),[])
    def test_unavailable_hypothetical_operand_rejected(self):self.assertFalse(self.solved('Step 1: 300 + 57 = 357',[3,5,7],357))
    def test_blank_lines_break_contiguity(self):self.assertFalse(self.solved('Step 1: 3 + 4 = 7\n\nStep 2: 7 * 2 = 14',[3,4,2],14))
    def test_no_search_for_missing_step(self):self.assertFalse(self.solved('Step 1: 7 * 2 = 14',[3,4,2],14))
    def test_baseline_accepted_content(self):self.assertTrue(c.accepted_content('{"moves":[{"i":0,"j":1,"op":"+"}]}',[3,4,2],7))
    def test_baseline_invalid_index_bool(self):self.assertFalse(c.accepted_content('{"moves":[{"i":true,"j":0,"op":"+"}]}',[3,4],7))
from fractions import Fraction
if __name__=='__main__':unittest.main()
